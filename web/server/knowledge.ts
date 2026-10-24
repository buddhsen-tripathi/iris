import { neon } from '@neondatabase/serverless';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { gzipSync } from 'node:zlib';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {createSnapshotCache,GRAPH_CACHE_TTL} from './knowledge-cache';
import { z } from 'zod';
import { graphEdgeSchema, passageSchema, evidenceResponseSchema, networkResponseSchema, type NetworkResponse } from '../src/lib/knowledge';

const MODEL = 'openai/text-embedding-3-small';
const DIMENSIONS = 1536;
const latest = `SELECT DISTINCT ON (entity_id) * FROM alphacouncil_graph.entity_snapshots WHERE first_observed_at_utc <= $1::timestamptz ORDER BY entity_id,first_observed_at_utc DESC,id DESC`;
const embeddingSchema = z.object({ data: z.array(z.object({ index: z.number().int(), embedding: z.array(z.number().finite()).length(DIMENSIONS) })).length(1) });
const requestSchema = z.object({
  q: z.string().trim().max(600).default(''),
  id: z.string().trim().max(300).default(''),
  as_of: z.iso.datetime({offset: true}).optional(),
  refresh: z.enum(['true','false']).default('false'),
});

export function fusePassages(lexical: z.infer<typeof passageSchema>[], semantic: z.infer<typeof passageSchema>[], limit = 12) {
  const merged = new Map<string, z.infer<typeof passageSchema>>();
  for (const [rows, method] of [[lexical, 'lexical'], [semantic, 'semantic']] as const) {
    rows.forEach((row,index) => {
      const previous = merged.get(row.id);
      const score = 1/(60+index+1);
      merged.set(row.id, previous ? {...previous, score:previous.score+score, matched_by:[...previous.matched_by,method]} : {...row,score,matched_by:[method]});
    });
  }
  return [...merged.values()].sort((a,b)=>b.score-a.score || a.id.localeCompare(b.id)).slice(0,limit);
}

export function createKnowledgeService(options: { databaseURL: string; apiKey?: string }) {
  const sql = neon(options.databaseURL);
  // The serving login has SELECT only; all SQL is fixed and values are bound.
  async function read(query: string, params: unknown[] = []) {
    const [rows] = await sql.transaction([sql.query(query,params)], { readOnly:true, fetchOptions:{signal:AbortSignal.timeout(15000)} });
    // The driver returns timestamptz as Date; the HTTP contract uses ISO strings.
    const serialized: unknown = JSON.parse(JSON.stringify(rows));
    return z.array(z.record(z.string(),z.unknown())).parse(serialized);
  }
  const cacheKey=createHash('sha256').update(options.databaseURL).digest('hex').slice(0,20);
  const snapshotCache=createSnapshotCache(resolve(process.cwd(),'../data/knowledge/cache/network-'+cacheKey+'.json'));
  async function network(observedAt?:string,force=false):Promise<NetworkResponse>{
    if(!observedAt)return snapshotCache.get(()=>network(new Date().toISOString()),force);
    const asOf=observedAt??new Date().toISOString();
    // One read-only repeatable-read transaction; no LIMIT and no neighborhood cap.
      const results=await sql.transaction([
        sql.query(`WITH s AS (${latest}) SELECT e.id,e.kind,s.name,s.aliases,s.identifiers->>'ticker' AS ticker
          FROM alphacouncil_graph.entities e JOIN s ON s.entity_id=e.id ORDER BY e.id`,[asOf]),
        sql.query(`SELECT e.id,e.subject_id,e.object_id,e.predicate,e.status
          FROM alphacouncil_graph.edges e JOIN alphacouncil_graph.documents d ON d.id=e.document_id
          WHERE e.first_observed_at_utc <= $1::timestamptz AND d.first_observed_at_utc <= $1::timestamptz
          AND (e.published_at_utc IS NULL OR e.published_at_utc <= $1::timestamptz)
          AND (d.published_at_utc IS NULL OR d.published_at_utc <= $1::timestamptz)
          AND (e.valid_from_utc IS NULL OR e.valid_from_utc <= $1::timestamptz)
          AND (e.valid_to_utc IS NULL OR e.valid_to_utc > $1::timestamptz) ORDER BY e.id`,[asOf]),
      ],{readOnly:true,isolationLevel:'RepeatableRead',fetchOptions:{signal:AbortSignal.timeout(20000)}});
      const data=networkResponseSchema.parse({nodes:results[0],edges:results[1],as_of:asOf,storage:'neon',complete:true});
      const ids=new Set(data.nodes.map(node=>node.id));
      if (data.edges.some(edge=>!ids.has(edge.subject_id)||!ids.has(edge.object_id))) throw new Error('Incomplete network snapshot');
      return data;
  }
  async function links(ids:string[],asOf:string) {
    if(!ids.length)return [];
    if(ids.length>40)throw new Error('Evidence batch exceeds limit');
    const rows=await read(`SELECT e.id,e.subject_id,e.object_id,e.predicate,e.status,e.evidence_quote,
      e.first_observed_at_utc,e.published_at_utc,e.valid_from_utc,e.valid_to_utc,e.metadata,
      d.source_url,d.title,d.source_name,d.content_sha256,p.page_number
      FROM alphacouncil_graph.edges e JOIN alphacouncil_graph.documents d ON d.id=e.document_id
      LEFT JOIN alphacouncil_graph.chunks c ON c.id=e.chunk_id LEFT JOIN alphacouncil_graph.pages p ON p.id=c.page_id
      WHERE e.id=ANY($2::text[]) AND e.first_observed_at_utc <= $1::timestamptz AND d.first_observed_at_utc <= $1::timestamptz
      AND (e.published_at_utc IS NULL OR e.published_at_utc <= $1::timestamptz)
      AND (d.published_at_utc IS NULL OR d.published_at_utc <= $1::timestamptz)
      AND (e.valid_from_utc IS NULL OR e.valid_from_utc <= $1::timestamptz)
      AND (e.valid_to_utc IS NULL OR e.valid_to_utc > $1::timestamptz)`,[asOf,ids]);
    return z.array(graphEdgeSchema).parse(rows);
  }
  async function link(id:string,asOf:string){
    return (await links([id],asOf))[0]??null;
  }
  const queryCache = new Map<string,{at:number;value:number[]}>();
  const pending = new Map<string,Promise<number[]>>();
  async function embedQuery(q: string) {
    const cached=queryCache.get(q);
    if(cached && Date.now()-cached.at<600000) return cached.value;
    const existing=pending.get(q);if(existing)return existing;
    const request=(async()=>{
      if(!options.apiKey)throw new Error('Embedding provider is not configured');
      const response=await fetch('https://openrouter.ai/api/v1/embeddings',{
        method:'POST',headers:{'Authorization':`Bearer ${options.apiKey}`,'Content-Type':'application/json'},
        body:JSON.stringify({model:MODEL,dimensions:DIMENSIONS,input:q,encoding_format:'float'}),signal:AbortSignal.timeout(12000),
      });
      if(!response.ok)throw new Error('Embedding provider unavailable');
      const data=embeddingSchema.parse(await response.json());
      if(data.data[0].index!==0 || !data.data[0].embedding.some(x=>x!==0)) throw new Error('Invalid query embedding');
      const value=data.data[0].embedding;
      if(queryCache.size>=128) { const key=queryCache.keys().next().value;if(key)queryCache.delete(key); }
      queryCache.set(q,{at:Date.now(),value});return value;
    })();
    pending.set(q,request);
    try{return await request;}finally{pending.delete(q);}
  }
  async function evidence(q: string, asOf: string) {
    const fields=`c.id,c.text,c.start_offset,c.end_offset,p.page_number,d.id AS document_id,d.title,d.source_url,d.source_name,d.content_sha256,d.first_observed_at_utc,d.published_at_utc,d.metadata->>'issuer_entity_id' AS issuer_entity_id`;
    const joins=`FROM alphacouncil_graph.chunks c JOIN alphacouncil_graph.pages p ON p.id=c.page_id JOIN alphacouncil_graph.documents d ON d.id=p.document_id`;
    const visible=`d.first_observed_at_utc <= $1::timestamptz AND (d.published_at_utc IS NULL OR d.published_at_utc <= $1::timestamptz)`;
    const lexicalPromise=read(`SELECT ${fields},0 AS score,ARRAY[]::text[] AS matched_by ${joins} WHERE ${visible} AND c.search @@ websearch_to_tsquery('english',$2) ORDER BY ts_rank_cd(c.search,websearch_to_tsquery('english',$2)) DESC,c.id LIMIT 30`,[asOf,q]);
    let warning: string|null=null;
    const semanticPromise=embedQuery(q).then(vector=>read(`SELECT ${fields},0 AS score,ARRAY[]::text[] AS matched_by ${joins}
      JOIN alphacouncil_graph.embeddings v ON v.chunk_id=c.id
      WHERE ${visible} AND v.first_observed_at_utc <= $1::timestamptz AND v.model=$3
      ORDER BY v.embedding <=> $2::vector,c.id LIMIT 30`,[asOf,JSON.stringify(vector),MODEL])).catch(()=>{warning='Semantic search is unavailable. Showing keyword results.';return [];});
    const [lexical,semantic]=await Promise.all([lexicalPromise,semanticPromise]);
    if (!semantic.length && !warning) warning='No semantic passages are available at this observation time. Showing keyword results.';
    return evidenceResponseSchema.parse({passages:fusePassages(z.array(passageSchema).parse(lexical),z.array(passageSchema).parse(semantic)),mode:warning?'lexical':'hybrid',warning,as_of:asOf});
  }
  return {evidence,network,link,links,cacheInfo:snapshotCache.info};
}

export function knowledgeMiddleware(options: { databaseURL?: string; apiKey?: string;service?:ReturnType<typeof createKnowledgeService>|null }) {
  const service=options.service??(options.databaseURL?createKnowledgeService({databaseURL:options.databaseURL,apiKey:options.apiKey}):null);
  let active=0;
  return async (req:IncomingMessage,res:ServerResponse,next:()=>void)=>{
    const url=new URL(req.url??'/','http://localhost');
    if(!url.pathname.startsWith('/knowledge/'))return next();
    const send=(status:number,body:unknown)=>{
      const json=JSON.stringify(body);
      if (json.length>40000 && /\bgzip\b/.test(req.headers['accept-encoding']??'')) {
        res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','Content-Encoding':'gzip','Vary':'Accept-Encoding'});
        res.end(gzipSync(json));
      } else { res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','Vary':'Accept-Encoding'});res.end(json); }
    };
    if(req.method!=='GET'){res.setHeader('Allow','GET');return send(405,{error:'Read-only endpoint'});}
    if(!service)return send(503,{error:'Configure KNOWLEDGE_DATABASE_URL and publish the evidence graph to Neon.'});
    if(active>=8)return send(429,{error:'Graph service is busy. Try again shortly.'});
    const parsed=requestSchema.safeParse(Object.fromEntries(url.searchParams));
    if(!parsed.success)return send(400,{error:'Invalid graph request parameters'});
    const args=parsed.data,asOf=args.as_of??new Date().toISOString();
    active++;
    try {
      if(url.pathname==='/knowledge/network'){
        const data=await service.network(args.as_of,args.refresh==='true');
        const etag=data.snapshot_id?`"${data.snapshot_id}"`:undefined;
        if(etag)res.setHeader('ETag',etag);
        res.setHeader('X-Knowledge-Cache',args.as_of?'historical':service.cacheInfo().source);
        res.setHeader('X-Knowledge-Cache-TTL',String(GRAPH_CACHE_TTL/1000));
        if(etag&&req.headers['if-none-match']===etag){res.writeHead(304,{'Cache-Control':'private, max-age=86400, must-revalidate'});res.end();return;}
        return send(200,data);
      }
      if(url.pathname==='/knowledge/link'){
        if(!args.id)return send(400,{error:'Choose an exact relationship ID'});
        const edge=await service.link(args.id,asOf);
        return edge?send(200,edge):send(404,{error:'Relationship was not observed at the requested time'});
      }
      if(url.pathname==='/knowledge/search'){
        if(args.q.length<2)return send(400,{error:'Enter at least two characters'});
        return send(200,await service.evidence(args.q,asOf));
      }
      return send(404,{error:'Unknown graph endpoint'});
    } catch {return send(503,{error:'Evidence graph is temporarily unavailable. Check the Neon import and database configuration.'});}
    finally{active--;}
  };
}

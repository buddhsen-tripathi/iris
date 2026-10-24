import {createHash,randomUUID} from 'node:crypto';
import {mkdir,readFile,rename,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {z} from 'zod';
import {safeSourceURL} from '../src/lib/knowledge';

export const EXA_PEOPLE_TTL=24*60*60_000;
export const MAX_PEOPLE_SEARCHES=3;
const hash=(text:string)=>createHash('sha256').update(text).digest('hex');
export const evidenceText=(text:string)=>text.normalize('NFKC').replace(/\s+/g,' ').trim();
const sourceSchema=z.object({id:z.string(),title:z.string(),url:z.url(),text:z.string(),published_at:z.string().nullable(),observed_at:z.iso.datetime(),content_hash:z.string()});
const resultSchema=z.object({query:z.string(),company_id:z.string(),sources:z.array(sourceSchema).max(5),fetched_at:z.iso.datetime(),provider_cost_usd:z.number().nonnegative().nullable(),notices:z.array(z.string())});
export type PeopleSearchResult=z.infer<typeof resultSchema>;
export type PeopleSearchInput={company_id:string;company_name:string;tickers:string[];person_name?:string};
export type PeopleSearch=(input:PeopleSearchInput,signal?:AbortSignal)=>Promise<PeopleSearchResult&{cached:boolean}>;
const responseSchema=z.object({
  results:z.array(z.object({title:z.string().nullable().optional(),url:z.string(),text:z.string().optional(),publishedDate:z.string().nullable().optional()})).max(100),
  costDollars:z.object({total:z.number().nonnegative().optional()}).optional(),
  notices:z.array(z.object({code:z.string(),message:z.string()})).optional(),
});
const cacheSchema=z.object({version:z.literal(1),key:z.string(),saved_at:z.number(),data:resultSchema});

export function peopleSearchQuery(input:PeopleSearchInput){
  const company=`${input.company_name}${input.tickers.length?` (${input.tickers.slice(0,3).join(', ')})`:''}`;
  return input.person_name
    ? `${input.person_name} ${company} professional biography company role past employers education research. Prefer official company biographies, filings and institutional sources; distinguish people with the same name and former roles.`
    : `${company} leadership founders executives board of directors key technical leaders professional biographies roles and previous experience. Prefer official company leadership pages, investor relations and filings.`;
}

export function normalizePeopleSearch(raw:unknown,input:PeopleSearchInput,observedAt:string):PeopleSearchResult{
  const data=responseSchema.parse(raw),seen=new Set<string>();
  const sources=data.results.flatMap(result=>{
    const url=safeSourceURL(result.url),text=evidenceText(result.text??'').slice(0,5000);
    if(!url||!text||seen.has(url))return [];seen.add(url);
    const published=result.publishedDate?Date.parse(result.publishedDate):NaN;
    const content_hash=hash(text);
    return [{id:`exa:${hash(url+'\n'+content_hash)}`,title:(result.title??url).slice(0,400),url,text,published_at:Number.isFinite(published)?new Date(published).toISOString():null,observed_at:observedAt,content_hash}];
  }).slice(0,5);
  return resultSchema.parse({query:peopleSearchQuery(input),company_id:input.company_id,sources,fetched_at:observedAt,provider_cost_usd:data.costDollars?.total??null,notices:(data.notices??[]).map(notice=>`${notice.code}: ${notice.message}`)});
}

export function createExaPeopleService({apiKey,cacheDirectory,fetch:doFetch=fetch,now=Date.now}:{apiKey:string;cacheDirectory?:string;fetch?:typeof fetch;now?:()=>number}){
  const memory=new Map<string,z.infer<typeof cacheSchema>>(),pending=new Map<string,Promise<PeopleSearchResult&{cached:boolean}>>();
  const search:PeopleSearch=async(input,signal)=>{
    signal?.throwIfAborted();
    const query=peopleSearchQuery(input),key=hash(JSON.stringify([1,input.company_id,query]));
    const path=cacheDirectory?join(cacheDirectory,key+'.json'):null;
    const fresh=(entry:z.infer<typeof cacheSchema>)=>entry.key===key&&entry.saved_at<=now()+60000&&now()-entry.saved_at<EXA_PEOPLE_TTL&&entry.data.sources.every(source=>hash(source.text)===source.content_hash&&safeSourceURL(source.url));
    const saved=memory.get(key);if(saved&&fresh(saved))return {...saved.data,cached:true};
    const inflight=pending.get(key);if(inflight)return inflight;
    const task=(async()=>{
      if(path){try{
        const disk=cacheSchema.parse(JSON.parse(await readFile(path,'utf8')));
        if(fresh(disk)){if(memory.size>=64)memory.delete(memory.keys().next().value??'');memory.set(key,disk);return {...disk.data,cached:true};}
      }catch{/* Missing or corrupt entries are fetched again. */}}
      signal?.throwIfAborted();
      const timeout=AbortSignal.timeout(20000);
      const response=await doFetch('https://api.exa.ai/search',{method:'POST',headers:{'x-api-key':apiKey,'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({query,type:'auto',numResults:5,contents:{text:{maxCharacters:5000}}}),signal:signal?AbortSignal.any([signal,timeout]):timeout});
      if(!response.ok){
        const message=response.status===401||response.status===403?'Exa rejected the server API key.':response.status===402?'Exa research credits are unavailable.':response.status===429?'Exa is rate limiting research. Try again shortly.':'Exa people research is temporarily unavailable.';
        throw new Error(message);
      }
      const data=normalizePeopleSearch(await response.json(),input,new Date(now()).toISOString());
      const entry={version:1,key,saved_at:now(),data};
      if(memory.size>=64)memory.delete(memory.keys().next().value??'');memory.set(key,cacheSchema.parse(entry));
      if(path&&cacheDirectory){try{
        await mkdir(cacheDirectory,{recursive:true,mode:0o700});const temporary=path+'.'+randomUUID()+'.tmp';
        await writeFile(temporary,JSON.stringify(entry),{mode:0o600});await rename(temporary,path);
      }catch{/* Research still works when the local cache is read-only. */}}
      return {...data,cached:false};
    })();
    pending.set(key,task);try{return await task;}finally{pending.delete(key);}
  };
  return {search};
}

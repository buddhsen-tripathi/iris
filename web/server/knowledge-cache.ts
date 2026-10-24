import {createHash,randomUUID} from 'node:crypto';
import {mkdir,readFile,rename,writeFile} from 'node:fs/promises';
import {dirname} from 'node:path';
import {z} from 'zod';
import {networkResponseSchema,type NetworkResponse} from '../src/lib/knowledge';

export const GRAPH_CACHE_TTL=24*60*60*1000;
const envelope=z.object({format:z.literal(1),saved_at:z.number().finite(),snapshot_id:z.string().regex(/^[a-f0-9]{64}$/),data:networkResponseSchema});
function snapshotId(data:NetworkResponse){return createHash('sha256').update(JSON.stringify([data.nodes,data.edges])).digest('hex');}

/** A private, atomic disk snapshot survives Vite restarts; source errors never overwrite it. */
export function createSnapshotCache(path:string,now=Date.now) {
  let record:z.infer<typeof envelope>|null=null;
  let hydrated=false;
  let pending:Promise<NetworkResponse>|null=null;
  let pendingRefresh=false;
  let source:'memory'|'disk'|'origin'='origin';
  async function hydrate(){
    if(hydrated)return;
    hydrated=true;
    try{
      const saved=envelope.parse(JSON.parse(await readFile(path,'utf8')));
      if(saved.saved_at>now()+60000 || snapshotId(saved.data)!==saved.snapshot_id)return;
      record={...saved,data:{...saved.data,snapshot_id:saved.snapshot_id}};
    }catch{/* Missing/corrupt caches are rebuilt from the source. */}
  }
  async function get(load:()=>Promise<NetworkResponse>,force=false):Promise<NetworkResponse>{
    if(pending){
      const refresh=pendingRefresh;
      const result=await pending;
      return force&&!refresh?get(load,true):result;
    }
    pendingRefresh=force;
    pending=(async()=>{
      const fromDisk=!hydrated;
      await hydrate();
      if(!force&&record&&now()-record.saved_at<GRAPH_CACHE_TTL){source=fromDisk?'disk':'memory';return record.data;}
      const fresh=networkResponseSchema.parse(await load());
      const id=snapshotId(fresh);
      // An unchanged corpus retains its original as_of and object identity.
      const data=record?.snapshot_id===id?record.data:{...fresh,snapshot_id:id};
      const next={format:1 as const,saved_at:now(),snapshot_id:id,data};
      const temporary=path+'.'+randomUUID()+'.tmp';
      try{
        await mkdir(dirname(path),{recursive:true,mode:0o700});
        await writeFile(temporary,JSON.stringify(next),{mode:0o600});
        await rename(temporary,path);
      }catch{/* A read-only filesystem still gets the in-memory cache. */}
      record=next;source='origin';return data;
    })();
    try{return await pending;}finally{pending=null;pendingRefresh=false;}
  }
  return {get,info:()=>({source,savedAt:record?.saved_at??null,expiresAt:record?record.saved_at+GRAPH_CACHE_TTL:null})};
}

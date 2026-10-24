import {z} from 'zod';
import {networkResponseSchema,type NetworkResponse} from './knowledge';

export const GRAPH_CACHE_TTL=24*60*60*1000;
const DB_NAME='alphacouncil-graph-v1';
const STORE='snapshots';
const recordSchema=z.object({format:z.literal(1),savedAt:z.number().finite(),etag:z.string().nullable(),data:networkResponseSchema});
type SavedGraph=z.infer<typeof recordSchema>;
let memory:SavedGraph|null=null;
let connection:Promise<IDBDatabase>|null=null;
async function database(){
  if(!connection)connection=new Promise<IDBDatabase>((resolve,reject)=>{
    const request=indexedDB.open(DB_NAME,1);
    request.onupgradeneeded=()=>request.result.createObjectStore(STORE);
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(new Error('Saved graph storage is unavailable'));
    request.onblocked=()=>reject(new Error('Saved graph storage is blocked'));
  }).catch(error=>{connection=null;throw error;});
  return connection;
}
export async function getGraphRecord(key:string):Promise<unknown>{
  try{
    const db=await database();
    return await new Promise<unknown>((resolve,reject)=>{
      const request=db.transaction(STORE,'readonly').objectStore(STORE).get(key);
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
    });
  }catch{return undefined;}
}
export async function setGraphRecord(key:string,value:unknown){
  try{
    const db=await database();
    await new Promise<void>((resolve,reject)=>{
      const transaction=db.transaction(STORE,'readwrite');transaction.objectStore(STORE).put(value,key);
      transaction.oncomplete=()=>resolve();transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error);
    });
  }catch{/* Private mode / storage quotas must not prevent graph access. */}
}
export function validSavedGraph(value:unknown,now=Date.now()){
  const parsed=recordSchema.safeParse(value);
  if(!parsed.success || parsed.data.savedAt>now+60000)return null;
  return parsed.data;
}
export function graphIsFresh(record:SavedGraph,now=Date.now()){return now-record.savedAt<GRAPH_CACHE_TTL;}
type GraphLoad={data:NetworkResponse;savedAt:number;source:'saved'|'network'|'offline';warning:string|null};

export async function loadGraphSnapshot(signal:AbortSignal,force=false):Promise<GraphLoad>{
  const cached=memory??validSavedGraph(await getGraphRecord('network'));
  if(cached)memory=cached;
  if(!force&&cached&&graphIsFresh(cached))return {data:cached.data,savedAt:cached.savedAt,source:'saved',warning:null};
  try{
    const response=await fetch('/knowledge/network'+(force?'?refresh=true':''),{
      signal:AbortSignal.any([signal,AbortSignal.timeout(30000)]),headers:cached?.etag?{'If-None-Match':cached.etag}:{},cache:'no-cache',
    });
    if(response.status===304&&cached){
      memory={...cached,savedAt:Date.now()};await setGraphRecord('network',memory);
      return {data:memory.data,savedAt:memory.savedAt,source:'saved',warning:null};
    }
    const raw:unknown=await response.json();
    if(!response.ok){const error=z.object({error:z.string()}).safeParse(raw);throw new Error(error.success?error.data.error:'Could not refresh the graph');}
    const data=networkResponseSchema.parse(raw);
    const next:SavedGraph={format:1,savedAt:Date.now(),etag:response.headers.get('ETag'),data:cached?.data.snapshot_id&&data.snapshot_id===cached.data.snapshot_id?cached.data:data};
    memory=next;await setGraphRecord('network',next);
    return {data:next.data,savedAt:next.savedAt,source:'network',warning:null};
  }catch(error){
    if(signal.aborted)throw error;
    if(cached&&!force)return {data:cached.data,savedAt:cached.savedAt,source:'offline',warning:'Showing the last saved graph. Refresh when the connection is available.'};
    throw error;
  }
}

export const savedLayoutSchema=z.object({version:z.literal(1),snapshotId:z.string(),positions:z.record(z.string(),z.object({x:z.number().finite(),y:z.number().finite()}))});

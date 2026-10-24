import {describe,expect,it} from 'vitest';
import {mkdtemp,readFile,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createSnapshotCache,GRAPH_CACHE_TTL} from './knowledge-cache';
import type {NetworkResponse} from '../src/lib/knowledge';

const data:NetworkResponse={nodes:[{id:'company:1',kind:'company',name:'A company',aliases:[],ticker:null}],edges:[],as_of:'2026-10-24T17:00:00Z',storage:'neon',complete:true};
async function temp(run:(path:string)=>Promise<void>){const dir=await mkdtemp(join(tmpdir(),'alphacouncil-cache-'));try{await run(join(dir,'snapshot.json'));}finally{await rm(dir,{recursive:true,force:true});}}

describe('persistent graph snapshots',()=>{
  it('reuses memory and survives a server restart without querying the source',()=>temp(async path=>{
    let calls=0;const load=async()=>{calls++;return data;};
    const first=createSnapshotCache(path);
    const initial=await first.get(load);
    expect(initial.snapshot_id).toMatch(/^[a-f0-9]{64}$/);
    expect(await first.get(load)).toBe(initial);expect(calls).toBe(1);
    const restarted=createSnapshotCache(path);
    expect(await restarted.get(async()=>{throw new Error('database offline');})).toEqual(initial);
    expect(restarted.info().source).toBe('disk');
  }));
  it('refreshes only on demand and retains snapshot identity and as_of when data did not change',()=>temp(async path=>{
    let calls=0;const cache=createSnapshotCache(path);
    const initial=await cache.get(async()=>{calls++;return data;});
    const refresh=await cache.get(async()=>{calls++;return {...data,as_of:'2026-10-25T00:00:00Z'};},true);
    expect(refresh).toBe(initial);expect(calls).toBe(2);
    const changed=await cache.get(async()=>({...data,nodes:[...data.nodes,{id:'company:2',kind:'company',name:'New issuer',aliases:[],ticker:null}]}),true);
    expect(changed.snapshot_id).not.toBe(initial.snapshot_id);expect(changed.nodes).toHaveLength(2);
  }));
  it('expires at 24 hours and never overwrites a good saved snapshot on source failure',()=>temp(async path=>{
    let now=100000;const cache=createSnapshotCache(path,()=>now);
    await cache.get(async()=>data);const before=await readFile(path,'utf8');
    now+=GRAPH_CACHE_TTL+1;
    await expect(cache.get(async()=>{throw new Error('offline');})).rejects.toThrow('offline');
    expect(await readFile(path,'utf8')).toBe(before);
    expect((await cache.get(async()=>data)).nodes).toHaveLength(1);
  }));
  it('rejects corrupted disk payloads instead of silently displaying altered evidence',()=>temp(async path=>{
    await createSnapshotCache(path).get(async()=>data);
    const saved=JSON.parse(await readFile(path,'utf8'));saved.data.nodes[0].name='corrupted';
    await writeFile(path,JSON.stringify(saved));let calls=0;
    const recovered=await createSnapshotCache(path).get(async()=>{calls++;return data;});
    expect(calls).toBe(1);expect(recovered.nodes[0].name).toBe('A company');
  }));
  it('deduplicates concurrent cold loads',()=>temp(async path=>{
    const cache=createSnapshotCache(path);let calls=0;
    const load=async()=>{calls++;return data;};
    const results=await Promise.all([cache.get(load),cache.get(load),cache.get(load)]);
    expect(calls).toBe(1);expect(results[1]).toBe(results[0]);
  }));
});

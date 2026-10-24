import {describe,expect,it} from 'vitest';
import {validSavedGraph,graphIsFresh,GRAPH_CACHE_TTL,savedLayoutSchema} from './graph-cache';
const saved={format:1,savedAt:100000,etag:'"snapshot"',data:{nodes:[],edges:[],as_of:'2026-10-24T17:00:00Z',storage:'neon',complete:true}};
describe('browser graph cache contracts',()=>{
  it('rejects incompatible and future-dated snapshots',()=>{
    expect(validSavedGraph({...saved,format:2},100000)).toBeNull();
    expect(validSavedGraph({...saved,savedAt:200001},100000)).toBeNull();
    expect(validSavedGraph({...saved,data:{...saved.data,complete:false}},100000)).toBeNull();
    expect(validSavedGraph(saved,100000)).not.toBeNull();
  });
  it('treats the saved corpus as fresh for 24 hours, not a one-minute polling window',()=>{
    const record=validSavedGraph(saved,100000);if(!record)throw new Error('Fixture is invalid');
    expect(graphIsFresh(record,100000+60*60000)).toBe(true);
    expect(graphIsFresh(record,100000+GRAPH_CACHE_TTL)).toBe(false);
  });
  it('refuses invalid layout coordinates rather than restarting from a corrupted position cache',()=>{
    expect(savedLayoutSchema.safeParse({version:1,snapshotId:'x',positions:{a:{x:NaN,y:1}}}).success).toBe(false);
    expect(savedLayoutSchema.safeParse({version:1,snapshotId:'x',positions:{a:{x:3,y:-2}}}).success).toBe(true);
  });
});

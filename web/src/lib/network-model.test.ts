import {describe,expect,it} from 'vitest';
import {indexNetwork,mapNetwork,researchDegree,searchNetwork} from './network-model';
import type {NetworkResponse} from './knowledge';

const fixture:NetworkResponse={
  storage:'neon',complete:true,as_of:'2026-10-24T17:00:00Z',
  nodes:[
    {id:'equity:NVDA',kind:'security',name:'NVIDIA common shares',ticker:'NVDA',aliases:['NVDA']},
    {id:'issuer:NVDA',kind:'company',name:'NVIDIA Corporation',ticker:null,aliases:['NVIDIA']},
    {id:'issuer:TSM',kind:'company',name:'Taiwan Semiconductor Manufacturing',ticker:null,aliases:['TSMC']},
    {id:'lei:unverified',kind:'legal_entity',name:'Unresolved legal entity',ticker:null,aliases:[]},
    {id:'issuer:isolated',kind:'company',name:'Isolated company',ticker:null,aliases:[]},
  ],
  edges:[
    {id:'listing',subject_id:'equity:NVDA',object_id:'issuer:NVDA',predicate:'ISSUED_BY',status:'reference'},
    {id:'manufacturing',subject_id:'issuer:TSM',object_id:'issuer:NVDA',predicate:'MANUFACTURES_FOR',status:'reported'},
    {id:'name-match',subject_id:'issuer:NVDA',object_id:'lei:unverified',predicate:'MATCHES_LEGAL_NAME',status:'candidate'},
  ],
};

describe('complete graph identity and coverage',()=>{
  it('resolves ticker search to listing-associated companies without merging legal-name candidates',()=>{
    const index=indexNetwork(fixture);
    const results=searchNetwork(index,'NVDA');
    expect(results[0].node.id).toBe('issuer:NVDA');
    expect(results.map(row=>row.node.id)).not.toContain('lei:unverified');
    expect(searchNetwork(index,'Taiwan manufacturing','company')[0].node.id).toBe('issuer:TSM');
    expect(searchNetwork(index,'isolated')[0].node.id).toBe('issuer:isolated');
  });
  it('keeps every parallel source assertion in the index',()=>{
    const edges=Array.from({length:260},(_,i)=>({...fixture.edges[1],id:`source-${i}`}));
    const index=indexNetwork({...fixture,edges:[fixture.edges[0],...edges]});
    expect(index.adjacent.get('issuer:NVDA')).toHaveLength(261);
  });
});

describe('mapNetwork', () => {
  const nodes = ['a', 'b', 'c', 's', 'z'].map((id) => ({ id, kind: id === 's' ? 'security' : 'company', name: id.toUpperCase(), aliases: [], ticker: null }));
  const edge = (id: string, subject_id: string, object_id: string, status: 'reported' | 'candidate' | 'reference', predicate = 'MENTIONS') => ({ id, subject_id, object_id, predicate, status });
  const data = {
    as_of: '2026-10-24T00:00:00Z', storage: 'neon', complete: true, snapshot_id: 'x', nodes,
    edges: [edge('1', 'a', 'b', 'candidate'), edge('2', 'b', 'a', 'candidate'), edge('3', 'a', 'b', 'reported', 'PARTNERS_WITH'), edge('4', 'b', 'c', 'candidate'), edge('5', 's', 'a', 'reference', 'ISSUED_BY')],
  } as unknown as Parameters<typeof mapNetwork>[0];
  const all = new Set(['reported', 'candidate', 'reference'] as const);

  it('defaults to research links, merging parallel assertions and keeping the strongest status', () => {
    const map = mapNetwork(data, all, 'research');
    expect(map.nodes.map((n) => n.id)).toEqual(['a', 'b', 'c']);
    const ab = map.edges.find((e) => [e.subject_id, e.object_id].sort().join('') === 'ab')!;
    expect([ab.count, ab.status, ab.id]).toEqual([3, 'reported', '3']);
    expect(map.degree.get('b')).toBe(2);
  });

  it('adds listings on request, and keeps unlinked records only in everything', () => {
    expect(mapNetwork(data, all, 'listings').nodes.map((n) => n.id)).toEqual(['a', 'b', 'c', 's']);
    expect(mapNetwork(data, all, 'everything').nodes).toHaveLength(5);
    expect(mapNetwork(data, new Set(['candidate'] as const), 'research').edges.every((e) => e.status === 'candidate')).toBe(true);
  });

  it('focuses on one entity and its direct neighbours', () => {
    expect(mapNetwork(data, all, 'research', 'c').nodes.map((n) => n.id)).toEqual(['b', 'c']);
  });

  it('ranks entities by distinct research neighbours', () => {
    expect(Object.fromEntries(researchDegree(data))).toEqual({ a: 1, b: 2, c: 1 });
  });
});

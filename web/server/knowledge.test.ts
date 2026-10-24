import { describe, expect, it } from 'vitest';
import { createServer } from 'node:http';
import { fusePassages, knowledgeMiddleware } from './knowledge';
import { safeSourceURL } from '../src/lib/knowledge';

const passage=(id:string)=>({id,text:'Source evidence',page_number:1,start_offset:0,end_offset:15,document_id:'document:1',title:'Annual report',source_url:'https://example.org/report',source_name:'Issuer',content_sha256:'a'.repeat(64),first_observed_at_utc:'2026-10-24T00:00:00Z',published_at_utc:null,score:0,matched_by:[]});

describe('hybrid evidence ranking',()=>{
  it('combines independent ranks, deduplicates passages and retains each retrieval method',()=>{
    const results=fusePassages([passage('lexical-only'),passage('both')],[passage('semantic-only'),passage('both')]);
    expect(results.map(p=>p.id)).toEqual(['both','lexical-only','semantic-only']);
    expect(results[0].matched_by).toEqual(['lexical','semantic']);
    expect(results[0].source_url).toBe('https://example.org/report');
  });
  it('bounds output without treating similarity as a financial impact weight',()=>{
    const results=fusePassages([passage('a'),passage('b')],[],1);
    expect(results).toHaveLength(1);
    expect(results[0].score).toBeCloseTo(1/61);
    expect(results[0]).not.toHaveProperty('expected_return');
  });
});

describe('source links',()=>{
  it('rejects executable and malformed links while preserving primary HTTPS sources',()=>{
    expect(safeSourceURL('javascript:alert(1)')).toBeNull();
    expect(safeSourceURL('data:text/html,hello')).toBeNull();
    expect(safeSourceURL('bad url')).toBeNull();
    expect(safeSourceURL('https://issuer.example/report')).toBe('https://issuer.example/report');
  });
});

describe('read-only graph HTTP boundary',()=>{
  it('refuses mutations and invalid traversal/time parameters before querying the database',async()=>{
    const middleware=knowledgeMiddleware({databaseURL:'postgresql://user:secret@ep-test.us-east-1.aws.neon.tech/test'});
    const server=createServer((req,res)=>void middleware(req,res,()=>{res.writeHead(404);res.end();}));
    await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));
    const address=server.address();
    if(!address||typeof address==='string')throw new Error('Test server has no TCP address');
    const base=`http://127.0.0.1:${address.port}`;
    try {
      expect((await fetch(base+'/knowledge/network',{method:'POST'})).status).toBe(405);
      expect((await fetch(base+'/knowledge/link?as_of=not-a-date')).status).toBe(400);
      expect((await fetch(base+'/knowledge/link')).status).toBe(400);
      expect((await fetch(base+'/knowledge/search?q=x')).status).toBe(400);
      expect((await fetch(base+'/knowledge/stats')).status).toBe(404);
      expect((await fetch(base+'/other')).status).toBe(404);
    }finally{await new Promise<void>(resolve=>server.close(()=>resolve()));}
  });
  it('reports missing configuration without exposing credentials or creating a local fallback',async()=>{
    const middleware=knowledgeMiddleware({});
    const server=createServer((req,res)=>void middleware(req,res,()=>res.end()));
    await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));
    const address=server.address();if(!address||typeof address==='string')throw new Error('No test address');
    try{
      const response=await fetch(`http://127.0.0.1:${address.port}/knowledge/network`);
      expect(response.status).toBe(503);
      expect(await response.text()).toContain('publish the evidence graph');
    }finally{await new Promise<void>(resolve=>server.close(()=>resolve()));}
  });
});

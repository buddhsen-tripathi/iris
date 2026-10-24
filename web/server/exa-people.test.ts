import {describe,expect,it,vi} from 'vitest';
import {mkdtemp,readdir,readFile,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createExaPeopleService,EXA_PEOPLE_TTL,normalizePeopleSearch,peopleSearchQuery} from './exa-people';

const input={company_id:'issuer:nvidia',company_name:'NVIDIA Corp',tickers:['NVDA']};
const raw={results:[{title:'Jensen Huang — NVIDIA',url:'https://www.nvidia.com/leadership/jensen-huang/',text:'Jensen Huang founded NVIDIA in 1993. He holds a degree from Oregon State University.',publishedDate:null}],costDollars:{total:.01}};
const at='2026-10-24T12:00:00.000Z';
async function temp(run:(dir:string)=>Promise<void>){const dir=await mkdtemp(join(tmpdir(),'alphacouncil-exa-'));try{await run(dir);}finally{await rm(dir,{recursive:true,force:true});}}
describe('Exa professional source retrieval',()=>{
  it('scopes leadership and named-person queries to the exact company and tickers',()=>{
    expect(peopleSearchQuery(input)).toContain('NVIDIA Corp (NVDA)');
    expect(peopleSearchQuery({...input,person_name:'Jensen Huang'})).toContain('Jensen Huang NVIDIA Corp (NVDA)');
  });
  it('preserves source observations separately from unknown publication dates and computes stable evidence IDs',()=>{
    const source=normalizePeopleSearch(raw,input,at).sources[0];
    expect(source.observed_at).toBe(at);expect(source.published_at).toBeNull();
    expect(source.id).toBe(normalizePeopleSearch(raw,input,'2026-10-25T00:00:00.000Z').sources[0].id);
    expect(source.content_hash).toMatch(/^[a-f0-9]{64}$/);
  });
  it('drops unsafe URLs, empty excerpts and duplicates without promoting search relevance to a role',()=>{
    const result=normalizePeopleSearch({results:[...raw.results,...raw.results,{url:'javascript:alert(1)',text:'not a source'},{url:'https://example.com/empty',text:''}]},input,at);
    expect(result.sources).toHaveLength(1);expect(result).not.toHaveProperty('people');
  });
  it('bounds source text and returns zero sources honestly',()=>{
    expect(normalizePeopleSearch({results:[{url:'https://example.com',text:'a'.repeat(8000)}]},input,at).sources[0].text).toHaveLength(5000);
    expect(normalizePeopleSearch({results:[]},input,at).sources).toEqual([]);
  });
  it('deduplicates cold calls, reuses memory, and persists sources across service restarts',()=>temp(async dir=>{
    const fetcher=vi.fn(async()=>Response.json(raw));
    const service=createExaPeopleService({apiKey:'test-key',cacheDirectory:dir,fetch:fetcher,now:()=>Date.parse(at)});
    const [first,second]=await Promise.all([service.search(input),service.search(input)]);
    expect(first.sources).toEqual(second.sources);expect((await service.search(input)).cached).toBe(true);expect(fetcher).toHaveBeenCalledTimes(1);
    const restarted=createExaPeopleService({apiKey:'test-key',cacheDirectory:dir,fetch:fetcher,now:()=>Date.parse(at)});
    expect((await restarted.search(input)).cached).toBe(true);expect(fetcher).toHaveBeenCalledTimes(1);
    const serialized=await readFile(join(dir,(await readdir(dir))[0]),'utf8');expect(serialized).not.toContain('test-key');
  }));
  it('expires after 24 hours, and scopes cached sources to company identity and person',async()=>{
    let now=Date.parse(at);const fetcher=vi.fn(async()=>Response.json(raw));
    const service=createExaPeopleService({apiKey:'test-key',fetch:fetcher,now:()=>now});
    await service.search(input);await service.search({...input,person_name:'Jensen Huang'});await service.search({...input,company_id:'another:issuer'});
    expect(fetcher).toHaveBeenCalledTimes(3);now+=EXA_PEOPLE_TTL+1;await service.search(input);expect(fetcher).toHaveBeenCalledTimes(4);
  });
  it('does not reuse corrupted text from disk',()=>temp(async dir=>{
    const fetcher=vi.fn(async()=>Response.json(raw)),options={apiKey:'test-key',cacheDirectory:dir,fetch:fetcher,now:()=>Date.parse(at)};
    await createExaPeopleService(options).search(input);
    const path=join(dir,(await readdir(dir))[0]),saved=JSON.parse(await readFile(path,'utf8'));saved.data.sources[0].text='altered';await writeFile(path,JSON.stringify(saved));
    await createExaPeopleService(options).search(input);expect(fetcher).toHaveBeenCalledTimes(2);
  }));
  it('keeps failures out of cache and never surfaces provider error bodies or credentials',async()=>{
    const fetcher=vi.fn(async()=>new Response('sensitive test-key diagnostic',{status:401}));
    const service=createExaPeopleService({apiKey:'test-key',fetch:fetcher});
    await expect(service.search(input)).rejects.toThrow('Exa rejected the server API key.');
    await expect(service.search(input)).rejects.not.toThrow('test-key');expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it('passes provider notices as data and rejects malformed responses',()=>{
    expect(normalizePeopleSearch({...raw,notices:[{code:'RESTRICTIONS_RELAXED',message:'Query constraints relaxed.'}]},input,at).notices).toEqual(['RESTRICTIONS_RELAXED: Query constraints relaxed.']);
    expect(()=>normalizePeopleSearch({results:'bad'},input,at)).toThrow();
  });
  it('does not start requests for an aborted question',async()=>{
    const fetcher=vi.fn(async()=>Response.json(raw)),controller=new AbortController();controller.abort();
    await expect(createExaPeopleService({apiKey:'test',fetch:fetcher}).search(input,controller.signal)).rejects.toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });
});

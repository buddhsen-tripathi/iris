import {describe,expect,it,vi} from 'vitest';
import {createStockPerformanceService,normalizeStockHistory,STOCK_HISTORY_TTL} from './stock-performance';
import {performanceSummary,performanceWindow} from '../src/lib/stock-performance';

const raw={chart:{result:[{meta:{symbol:'MU',currency:'USD',instrumentType:'EQUITY',fullExchangeName:'NasdaqGS',longName:'Micron Technology'},timestamp:[Date.parse('2026-07-23')/1000,Date.parse('2026-07-24')/1000,Date.parse('2026-09-23')/1000,Date.parse('2026-10-22')/1000,Date.parse('2026-10-23')/1000],indicators:{quote:[{close:[100,110,null,99,121]}]}}]}};
const at='2026-10-24T12:00:00.000Z';
describe('listed stock performance',()=>{
  it('requires an exact listing identity and an equity instrument',()=>{
    expect(normalizeStockHistory(raw,'MU',at).source).toBe('Yahoo Finance');
    expect(()=>normalizeStockHistory(raw,'TSM',at)).toThrow('identity');
    const token=structuredClone(raw);token.chart.result[0].meta.instrumentType='CRYPTOCURRENCY';
    expect(()=>normalizeStockHistory(token,'MU',at)).toThrow();
  });
  it('preserves missing observations and rejects unordered or misaligned histories',()=>{
    expect(normalizeStockHistory(raw,'MU',at).points[2].close).toBeNull();
    const broken=structuredClone(raw);broken.chart.result[0].timestamp.reverse();
    expect(()=>normalizeStockHistory(broken,'MU',at)).toThrow('unordered');
    broken.chart.result[0].timestamp.pop();expect(()=>normalizeStockHistory(broken,'MU',at)).toThrow('Incomplete');
  });
  it('anchors returns to displayed trading dates and never treats a missing close as zero',()=>{
    const data=normalizeStockHistory(raw,'MU',at);
    const points=performanceWindow(data,'3M');
    expect(points[0].date).toBe('2026-07-23');
    expect(performanceSummary(points)?.change).toBeCloseTo(21);
    expect(performanceSummary(performanceWindow(data,'1M'))?.change).toBeCloseTo(10);
    expect(performanceSummary([{date:'2026-10-23',close:121}])).toBeNull();
  });
  it('deduplicates concurrent fetches, reuses cached history, and expires it after 15 minutes',async()=>{
    let now=Date.parse(at);const fetcher=vi.fn(async()=>Response.json(raw));
    const service=createStockPerformanceService({fetch:fetcher,now:()=>now});
    const [one,two]=await Promise.all([service.history('MU'),service.history('MU')]);
    expect(one).toBe(two);expect(await service.history('MU')).toBe(one);expect(fetcher).toHaveBeenCalledTimes(1);
    now+=STOCK_HISTORY_TTL+1;await service.history('MU');expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it('rejects provider failures and invalid symbols without inventing data',async()=>{
    const fetcher=vi.fn(async()=>new Response('',{status:429}));const service=createStockPerformanceService({fetch:fetcher});
    await expect(service.history('../MU')).rejects.toThrow('Invalid');expect(fetcher).not.toHaveBeenCalled();
    await expect(service.history('MU')).rejects.toThrow('unavailable');
    await expect(service.history('MU')).rejects.toThrow('unavailable');expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

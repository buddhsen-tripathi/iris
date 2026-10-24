import {z} from 'zod';

export const stockHistorySchema=z.object({
  symbol:z.string(),providerSymbol:z.string(),name:z.string(),currency:z.string(),exchange:z.string(),
  source:z.literal('Yahoo Finance'),sourceURL:z.url(),fetchedAt:z.iso.datetime(),
  points:z.array(z.object({date:z.iso.date(),close:z.number().positive().nullable()})).min(2).max(400),
});
export type StockHistory=z.infer<typeof stockHistorySchema>;
export type PerformanceRange='1M'|'3M'|'1Y';

// Anchor to the latest reported trading date, not the browser's clock (weekends/holidays).
export function performanceWindow(history:StockHistory,range:PerformanceRange){
  const last=history.points.findLast(point=>point.close!==null);
  if(!last)return [];
  const end=new Date(`${last.date}T00:00:00Z`),cutoff=new Date(end);
  const months=range==='1M'?1:range==='3M'?3:12;
  cutoff.setUTCDate(1);cutoff.setUTCMonth(cutoff.getUTCMonth()-months);
  const monthEnd=new Date(Date.UTC(cutoff.getUTCFullYear(),cutoff.getUTCMonth()+1,0)).getUTCDate();
  cutoff.setUTCDate(Math.min(end.getUTCDate(),monthEnd));
  const boundary=cutoff.toISOString().slice(0,10);
  const start=history.points.findLastIndex(point=>point.date<=boundary&&point.close!==null);
  return history.points.slice(Math.max(0,start)).filter(point=>point.date<=last.date);
}

export function performanceSummary(points:StockHistory['points']){
  const first=points.find(point=>point.close!==null),last=points.findLast(point=>point.close!==null);
  if(first?.close==null||last?.close==null||first===last)return null;
  return {first,last,change:(last.close/first.close-1)*100};
}

export async function loadStockHistory(symbol:string,signal:AbortSignal){
  const response=await fetch(`/stock-performance?symbol=${encodeURIComponent(symbol)}`,{signal});
  if(!response.ok)throw new Error(response.status===404?'Price history is unavailable for this listing.':'Price history is temporarily unavailable.');
  return stockHistorySchema.parse(await response.json());
}

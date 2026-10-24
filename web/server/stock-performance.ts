import type {IncomingMessage,ServerResponse} from 'node:http';
import {z} from 'zod';
import {stockHistorySchema,type StockHistory} from '../src/lib/stock-performance';

const yahooSchema=z.object({chart:z.object({result:z.array(z.object({
  meta:z.object({symbol:z.string(),currency:z.string(),instrumentType:z.enum(['EQUITY','ETF']),fullExchangeName:z.string(),longName:z.string().optional(),shortName:z.string().optional()}),
  timestamp:z.array(z.number().int().positive()).max(400),
  indicators:z.object({quote:z.array(z.object({close:z.array(z.number().nullable()).max(400)})).min(1)}),
})).nullable()})});
export function normalizeStockHistory(raw:unknown,symbol:string,fetchedAt:string):StockHistory{
  const result=yahooSchema.parse(raw).chart.result?.[0];
  if(!result||result.meta.symbol!==symbol.replaceAll('.','-'))throw new Error('Listing identity could not be verified');
  const prices=result.indicators.quote[0]?.close??[];
  if(prices.length!==result.timestamp.length)throw new Error('Incomplete price history');
  const points=result.timestamp.map((time,i)=>({date:new Date(time*1000).toISOString().slice(0,10),close:prices[i]!=null&&prices[i]>0?prices[i]:null}));
  if(points.filter(point=>point.close!==null).length<2||points.some((point,i)=>i>0&&point.date<=(points[i-1]?.date??'')))throw new Error('Insufficient or unordered price history');
  return stockHistorySchema.parse({symbol,providerSymbol:result.meta.symbol,name:result.meta.longName??result.meta.shortName??symbol,currency:result.meta.currency,exchange:result.meta.fullExchangeName,source:'Yahoo Finance',sourceURL:`https://finance.yahoo.com/quote/${encodeURIComponent(result.meta.symbol)}/history/`,fetchedAt,points});
}

export const STOCK_HISTORY_TTL=15*60_000;
export function createStockPerformanceService({fetch:doFetch=fetch,now=Date.now}:{fetch?:typeof fetch;now?:()=>number}={}){
  const cache=new Map<string,{at:number;data:StockHistory}>(),inflight=new Map<string,Promise<StockHistory>>();
  async function history(symbol:string){
    if(!/^[A-Z][A-Z0-9.-]{0,14}$/.test(symbol))throw new Error('Invalid stock symbol');
    const saved=cache.get(symbol);if(saved&&now()-saved.at<STOCK_HISTORY_TTL)return saved.data;
    const pending=inflight.get(symbol);if(pending)return pending;
    const task=(async()=>{
      // Listed-equity daily closes. Never substitute the trading desk's tokenized instruments.
      // Yahoo's public chart endpoint is unofficial and can throttle; callers show unavailable states.
      const response=await doFetch(`https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol.replaceAll('.','-'))}?range=1y&interval=1d`,{headers:{'User-Agent':'Mozilla/5.0',Accept:'application/json'},signal:AbortSignal.timeout(12000)});
      if(!response.ok)throw new Error('Stock history provider unavailable');
      const data=normalizeStockHistory(await response.json(),symbol,new Date(now()).toISOString());
      if(cache.size>=256)cache.delete(cache.keys().next().value??'');
      cache.set(symbol,{at:now(),data});return data;
    })();
    inflight.set(symbol,task);try{return await task;}finally{inflight.delete(symbol);}
  }
  return {history};
}

export function stockPerformanceMiddleware(service=createStockPerformanceService()){
  return async(req:IncomingMessage,res:ServerResponse,next:()=>void)=>{
    const url=new URL(req.url??'/', 'http://local');if(url.pathname!=='/stock-performance')return next();
    const send=(status:number,body:unknown)=>{res.statusCode=status;res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control',status===200?'private, max-age=900':'no-store');res.end(JSON.stringify(body));};
    if(req.method!=='GET')return send(405,{message:'Only GET is supported.'});
    const symbol=(url.searchParams.get('symbol')??'').toUpperCase();
    if(!/^[A-Z][A-Z0-9.-]{0,14}$/.test(symbol))return send(400,{message:'Invalid stock symbol.'});
    try{return send(200,await service.history(symbol));}catch{return send(502,{message:'Price history is unavailable for this listing.'});}
  };
}

import {useQuery} from '@tanstack/react-query';
import {ExternalLink,LoaderCircle,RefreshCw} from 'lucide-react';
import {useId,useState} from 'react';
import {pct,price} from '@/lib/format';
import {loadStockHistory,performanceSummary,performanceWindow,type PerformanceRange,type StockHistory} from '@/lib/stock-performance';

const RANGES:PerformanceRange[]=['1M','3M','1Y'];
const dateLabel=(date:string)=>new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});

function PerformancePlot({points,symbol}:{points:StockHistory['points'];symbol:string}){
  const [hover,setHover]=useState<number|null>(null),id=useId();
  const values=points.flatMap(point=>point.close===null?[]:[point.close]);
  const min=Math.min(...values),max=Math.max(...values),span=max-min||max*.02||1;
  const low=min-span*.12,high=max+span*.12;
  const first=points[0],last=points.at(-1);
  if(!first||!last)return null;
  const start=Date.parse(first.date),duration=Date.parse(last.date)-start||1;
  const x=(date:string)=>8+(Date.parse(date)-start)/duration*384;
  const y=(value:number)=>12+(high-value)/(high-low)*124;
  let drawing=false;
  const path=points.map(point=>{if(point.close===null){drawing=false;return '';}const command=drawing?'L':'M';drawing=true;return `${command}${x(point.date).toFixed(2)},${y(point.close).toFixed(2)}`;}).join(' ');
  const active=hover===null?undefined:points[hover];
  function inspect(clientX:number,box:DOMRect){
    const target=start+Math.max(0,Math.min(1,((clientX-box.left)/box.width*440-8)/384))*duration;
    let nearest=0;points.forEach((point,i)=>{if(Math.abs(Date.parse(point.date)-target)<Math.abs(Date.parse(points[nearest]?.date??first.date)-target))nearest=i;});setHover(nearest);
  }
  return <>
    <div className="stock-performance-hover">{active?`${dateLabel(active.date)} · ${active.close===null?'No reported close':price(active.close,2)}`:'Daily close · Hover or use arrow keys to inspect'}</div>
    <svg viewBox="0 0 440 165" role="img" aria-labelledby={`${id}-title ${id}-desc`} tabIndex={0} onPointerMove={event=>inspect(event.clientX,event.currentTarget.getBoundingClientRect())} onPointerLeave={()=>setHover(null)} onFocus={()=>setHover(points.length-1)} onBlur={()=>setHover(null)} onKeyDown={event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();setHover(current=>event.key==='Home'?0:event.key==='End'?points.length-1:Math.max(0,Math.min(points.length-1,(current??points.length-1)+(event.key==='ArrowLeft'?-1:1))));}}>
      <title id={`${id}-title`}>{symbol} historical stock price</title><desc id={`${id}-desc`}>Daily closing prices from {dateLabel(first.date)} to {dateLabel(last.date)}. Use left and right arrow keys to inspect each date.</desc>
      {[min,max].map((value,i)=><g key={i}><line x1="8" x2="392" y1={y(value)} y2={y(value)} className="stock-performance-grid"/><text x="400" y={y(value)+3}>{price(value,2)}</text></g>)}
      {first.close!==null&&<line x1="8" x2="392" y1={y(first.close)} y2={y(first.close)} className="stock-performance-baseline"/>}
      <path d={path} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"/>
      {active&&<g><line x1={x(active.date)} x2={x(active.date)} y1="8" y2="139" className="stock-performance-baseline"/>{active.close!==null&&<circle cx={x(active.date)} cy={y(active.close)} r="3.5" fill="currentColor"/>}</g>}
      <text x="8" y="159">{dateLabel(first.date)}</text><text x="392" y="159" textAnchor="end">{dateLabel(last.date)}</text>
    </svg>
  </>;
}

export function StockPerformance({symbols}:{symbols:string[]}){
  const [selected,setSelected]=useState(symbols[0]??''),[range,setRange]=useState<PerformanceRange>('3M');
  const id=useId(),symbol=symbols.includes(selected)?selected:symbols[0]??'';
  const history=useQuery({queryKey:['listed-stock-performance',symbol],queryFn:({signal})=>loadStockHistory(symbol,signal),enabled:!!symbol,staleTime:15*60_000,gcTime:24*60*60_000,refetchOnWindowFocus:false,retry:1});
  const points=history.data?performanceWindow(history.data,range):[],summary=performanceSummary(points);
  if(!symbol)return null;
  return <section className="stock-performance" aria-label={`${symbol} stock performance`}>
    <header><span>PRICE PERFORMANCE</span>{symbols.length>1&&<select aria-label="Stock listing" value={symbol} onChange={event=>setSelected(event.target.value)}>{symbols.map(ticker=><option key={ticker}>{ticker}</option>)}</select>}<div role="group" aria-label={`${symbol} performance range`}>{RANGES.map(value=><button type="button" key={value} aria-pressed={range===value} onClick={()=>setRange(value)}>{value}</button>)}</div></header>
    {history.isPending&&<div className="stock-performance-state" role="status"><LoaderCircle size={14} className="animate-spin"/>Loading {symbol} price history…</div>}
    {history.isError&&!history.data&&<div className="stock-performance-state"><p>Price history is unavailable for {symbol}.</p><button type="button" disabled={history.isFetching} onClick={()=>void history.refetch()}><RefreshCw size={11}/>Retry</button></div>}
    {history.data&&summary&&<>
      <div className="stock-performance-value"><strong>{price(summary.last.close??undefined,2)} <small>{history.data.currency}</small></strong><span className={summary.change>=0?'stock-performance-up':'stock-performance-down'}>{pct(summary.change)} <small>over shown period</small></span></div>
      <div className={summary.change>=0?'stock-performance-up':'stock-performance-down'}><PerformancePlot key={`${symbol}:${range}`} points={points} symbol={symbol}/></div>
      <p id={id} className="stock-performance-note">{history.data.name} · {history.data.exchange}<br/>As of {dateLabel(summary.last.date)} · Split-adjusted close, excludes dividends.</p>
      <footer><a href={history.data.sourceURL} target="_blank" rel="noreferrer">Yahoo Finance<ExternalLink size={10}/></a><span title={history.data.fetchedAt}>Fetched {new Date(history.data.fetchedAt).toLocaleString()}</span></footer>
      {history.isError&&<p className="stock-performance-note">Refresh failed. Showing previously fetched history.</p>}
    </>}
    {history.data&&!summary&&<p className="stock-performance-state">Not enough reported closes for this period.</p>}
  </section>;
}

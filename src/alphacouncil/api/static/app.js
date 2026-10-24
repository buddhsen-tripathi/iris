'use strict';
const $ = id => document.getElementById(id);
const names = {lightgbm:'LightGBM',ridge:'Ridge',kalman:'Kalman',mean_reversion:'Mean reversion',momentum:'Momentum',committee:'Equal committee',adaptive:'Adaptive shadow'};
const colors = {lightgbm:'#be7448',ridge:'#54869a',kalman:'#aa9e60',mean_reversion:'#8b769c',momentum:'#87967b',committee:'#254f36',adaptive:'#92a52d'};
let mode = 'model', state = {}, generation = 0;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (value, digits=2) => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits});
const signed = (value,digits=4) => value == null ? '—' : `${value>=0?'+':''}${num(value,digits)}`;
const date = value => value ? new Date(value).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '—';
const percent = value => value == null ? '—' : `${num(value*100,1)}%`;
const policyName = value => ({five_minute_only:'5m entry',with_15m_30m_confirmation:'5m + 15/30m confirmation',forced_long_20s:'Forced long · 20s'}[value] || value);
const empty = (id, text) => $(id).innerHTML = `<div class="empty">${esc(text)}</div>`;
async function get(path) { const response=await fetch(path,{cache:'no-store'}); if(!response.ok)throw new Error(`${path}: ${response.status}`); return response.json(); }
function lineChart(id, series, opts={}) {
  const data=series.filter(s=>s.points?.length);
  if(!data.length){empty(id,opts.empty || 'No observed data yet.');return;}
  const width=650,height=opts.height || 225,left=48,right=14,top=15,bottom=31;
  const all=data.flatMap(s=>s.points);let xmin=Math.min(...all.map(p=>p.x)),xmax=Math.max(...all.map(p=>p.x)),ymin=Math.min(...all.map(p=>p.y)),ymax=Math.max(...all.map(p=>p.y));
  if(opts.zero){ymin=Math.min(0,ymin);ymax=Math.max(0,ymax);}
  if(xmax===xmin)xmax=xmin+1;
  const delta=ymax-ymin || Math.max(Math.abs(ymax)*.001,.1);ymin-=delta*.18;ymax+=delta*.18;
  const x=v=>left+(v-xmin)/(xmax-xmin)*(width-left-right),y=v=>height-bottom-(v-ymin)/(ymax-ymin)*(height-top-bottom);
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(opts.title || 'Observed series')}">`;
  for(let i=0;i<5;i++){const v=ymin+(ymax-ymin)*i/4;svg+=`<line class="grid" x1="${left}" y1="${y(v)}" x2="${width-right}" y2="${y(v)}"/><text text-anchor="end" x="${left-9}" y="${y(v)+3}">${num(v,opts.decimals ?? 1)}</text>`;}
  if(ymin<0&&ymax>0)svg+=`<line class="zero" x1="${left}" y1="${y(0)}" x2="${width-right}" y2="${y(0)}"/>`;
  const ticks=opts.ticks || [xmin,xmin+(xmax-xmin)/2,xmax];
  ticks.forEach(v=>svg+=`<text x="${x(v)}" y="${height-8}" text-anchor="middle">${esc(opts.tick ? opts.tick(v) : v+'m')}</text>`);
  data.forEach(s=>{const points=s.points.map(p=>`${x(p.x)},${y(p.y)}`).join(' ');svg+=`<polyline class="line ${s.key==='committee'?'committee-line':''}" stroke="${s.color || colors[s.key]}" ${s.dashed?'stroke-dasharray="5 4"':''} points="${points}"/>`;s.points.forEach(p=>svg+=`<circle cx="${x(p.x)}" cy="${y(p.y)}" r="${s.key==='committee'?3:2}" fill="${s.color || colors[s.key]}"><title>${esc(s.label || names[s.key] || s.key)}: ${num(p.y,3)}</title></circle>`);});
  svg+='</svg>';$(id).innerHTML=svg;
}
function renderForecasts(committee) {
  const forecasts=committee.fixed_forecasts || [], shadow=committee.adaptive;
  $('forecast-legend').innerHTML=[...Object.keys(names).filter(k=>k!=='adaptive'),...(shadow?.latest_forecasts?.length?['adaptive']:[])].map(key=>`<span><i style="background:${colors[key]}"></i>${esc(names[key])}</span>`).join('');
  const series=Object.keys(names).filter(k=>k!=='adaptive').map(key=>({key,points:[{x:0,y:0},...forecasts.map(f=>({x:f.horizon,y:(key==='committee'?f.predictions.committee_mu:f.predictions.experts[key])*10000}))]}));
  if(!forecasts.length){empty('forecast-chart','No prospective forecast bundle has been published.');$('horizon-strip').innerHTML='';}
  else {
    const anchor=forecasts[0].anchor_utc;
    const matching=(shadow?.latest_forecasts || []).filter(f=>f.anchor_utc===anchor);
    if(matching.length)series.push({key:'adaptive',dashed:true,points:[{x:0,y:0},...matching.map(f=>({x:f.horizon,y:f.adaptive_mu*10000}))]});
    lineChart('forecast-chart',series,{zero:true,ticks:[0,5,15,30],title:'Expert log return forecasts at trained horizons'});
    $('forecast-caption').textContent=`Model snapshot anchored ${date(anchor)} local. Published ${date(forecasts[0].published_at_utc)}. Points are 0 / 5 / 15 / 30 minutes; lines are visual guides. ${mode==='forced'?'These forecasts do not drive the forced-entry experiment.':''}`;
    $('horizon-strip').innerHTML=forecasts.map(f=>`<div><span>${f.horizon} MIN · FIXED COMMITTEE</span><strong class="${f.predictions.committee_mu>=0?'positive':'negative'}">${signed(f.predictions.committee_mu*10000,2)} <small>bp</small></strong></div>`).join('');
  }
  const adaptive=shadow?.weights_by_horizon?.['5'];
  $('weights').innerHTML=Object.entries(committee.fixed_weights || {}).map(([key,value])=>`<div class="weight-row"><div class="expert-name"><i class="expert-dot" style="background:${colors[key]}"></i>${esc(names[key] || key)}</div><div class="weight-value">${percent(value)}</div><div class="weight-value">${percent(adaptive?.[key])}<div class="bar-track"><div class="bar-fill" style="width:${Math.max(0,Math.min(100,(adaptive?.[key] || 0)*100))}%"></div></div></div></div>`).join('');
  $('shadow-note').textContent=shadow?`SHADOW ONLY · ${shadow.updates_by_horizon?.['5'] ?? 0} matured 5m updates. ${committee.adaptive_freshness.stale?'Heartbeat stale. ':''}Weights learn from first-observed outcomes; they do not place trades.`:'The adaptive shadow has not published a snapshot. Fixed weights remain 20% per expert.';
}
function renderPerformance(performance) {
  const accounts=performance.accounts || [],pnl=accounts.reduce((a,x)=>a+x.realized_pnl_usdt,0);
  $('pnl').textContent=accounts.length?`${signed(pnl)} USDT`:'—';$('pnl').className=pnl<0?'negative':'positive';
  $('pnl-detail').textContent=accounts.length===2?'Two separate 50 USDT paper portfolios':'50 USDT paper portfolio · after assumed costs';
  $('trades').textContent=`${accounts.reduce((a,x)=>a+x.completed_trades,0)} / ${accounts.reduce((a,x)=>a+x.open_positions,0)}`;
  const curves=accounts.map((a,i)=>({key:a.policy,label:policyName(a.policy),color:i===0?'#477953':'#be7448',points:[{x:new Date(state.overview.sessions[mode].started_at_utc || new Date()).getTime(),y:a.initial_cash_usdt},...performance.realized_equity.filter(x=>x.policy===a.policy).map(x=>({x:new Date(x.time_utc).getTime(),y:x.realized_equity_usdt}))]}));
  if(performance.realized_equity.length)lineChart('equity-chart',curves,{height:180,decimals:2,tick:v=>new Date(v).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'}),title:'Simulated realized equity in USDT'});
  else empty('equity-chart','No closed trades yet. Each paper portfolio starts with 50 USDT.');
  $('equity-title').textContent=mode==='forced'?'The cost of continuous turnover.':'Realized paper equity.';
  $('cost-line').textContent=mode==='forced'?`Assumed fees: ${num(performance.assumed_fees_paid_usdt,4)} USDT  /  Assumed slippage: ${num(performance.assumed_slippage_cost_usdt,4)} USDT. Mark-to-liquidation: ${num(performance.liquidation_equity_usdt_estimate,4)} USDT (quote ${date(performance.equity_quote_observed_at_utc)}).`:'Each policy starts with 50 USDT. Entry cap: 10 USDT. Assumptions: 10 bp fee + 2 bp slippage per side; spread paid at observed quotes.';
  const metrics=state.modelPerformance.forecast_metrics || [];
  $('metrics').innerHTML=[5,15,30].map(h=>{const m=metrics.find(m=>m.horizon_minutes===h&&m.model==='committee');return `<tr><td>${h} minutes</td><td class="num">${m?.rows ?? 0}</td><td class="num">${num(m?.mae_log_bps)}</td><td class="num">${percent(m?.directional_hit_rate)}</td></tr>`;}).join('');
  const shadow=state.committee.adaptive;
  $('adaptive-metrics').textContent=shadow?`Adaptive shadow: ${shadow.counts?.forecasts ?? 0} forecasts, ${shadow.counts?.outcomes ?? 0} observed outcomes. Separate from fixed committee scores above.`:'';
}
function renderDecisions(result) {
  $('decisions').innerHTML=result.decisions.length?result.decisions.slice(0,12).map(d=>`<tr data-id="${d.id}" tabindex="0" role="button" aria-label="Inspect decision ${d.id}"><td class="num">${esc(date(d.time_utc))}</td><td>${esc(policyName(d.policy))}</td><td><span class="action ${d.action==='PAPER_BUY'?'buy':''}">${esc(d.action)}</span></td><td class="reason">${esc(d.reason.replaceAll('_',' '))}</td><td class="num ${d.net_pnl<0?'negative':''}">${d.net_pnl==null?'—':signed(d.net_pnl)}</td><td>↗</td></tr>`).join(''):'<tr><td colspan="6">No decisions recorded in this experiment.</td></tr>';
  document.querySelectorAll('[data-id]').forEach(row=>{row.onclick=()=>showAutopsy(row.dataset.id);row.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showAutopsy(row.dataset.id);}};});
}
function renderNews(data) {
  const events=data.events || data.articles || [];
  $('news').innerHTML=events.length?events.slice(0,4).map(item=>{let url;try{url=new URL(item.source_url);if(!['http:','https:'].includes(url.protocol))return '';}catch{return '';}
    return `<a class="news-item" href="${esc(url.href)}" target="_blank" rel="noreferrer"><div class="news-source">${esc(item.source_name || 'PRIMARY SOURCE')} · ${esc(item.published_at_utc ? new Date(item.published_at_utc).toLocaleDateString() : 'DATE UNAVAILABLE')} ↗</div><div class="news-title">${esc(item.headline)}</div></a>`;}).join(''):`<p class="caption">${data.status==='complete' || data.feeds?.some(f=>f.status==='available')?'No headlines within the freshness window. Older source items are excluded.':'No source-backed headlines are available from the current feed snapshot.'} Grok / Jev connectors are not connected.</p>`;
}
async function refresh() {
  const request=++generation;
  try {
    const [overview,committee,performance,modelPerformance,decisions,news,risk,regime]=await Promise.all([get('/api/v1/overview'),get('/api/v1/committee/BTCUSDT/latest'),get(`/api/v1/performance?mode=${mode}`),get('/api/v1/performance?mode=model'),get(`/api/v1/decisions?mode=${mode}&limit=12`),get('/api/v1/news/BTCUSDT'),get('/api/v1/risk/latest'),get('/api/v1/regime/latest')]);
    if(request!==generation)return;state={overview,committee,performance,modelPerformance};
    const session=overview.sessions[mode],quote=session.quote,fresh=session.freshness;
    $('clock').textContent=`LEDGER SNAPSHOT ${date(overview.as_of_utc)} LOCAL`;
    $('session-id').textContent=`SESSION / ${session.session_id || 'UNAVAILABLE'}`;
    $('mode-note').textContent=mode==='model'?`Fixed committee · one forecast bundle per completed 5m bar. Session ${fresh.status}.`:`One forced long entry every 20s, subject to quote and size checks. Model signals are ignored. Session ${fresh.status}.`;
    $('price').textContent=quote?`$${num(quote.mid)}`:'—';
    $('quote-label').textContent=quote?.stale?'RECORDED QUOTE':'OBSERVED QUOTE';
    $('quote-detail').textContent=quote?`BID ${num(quote.bid)} / ASK ${num(quote.ask)} · ${num(quote.receipt_age_seconds,0)}s old · RTT ${num(quote.rtt_seconds,2)}s`:'Quote unavailable · waiting for receipts';
    const counts=overview.sessions.model.counts;
    $('forecasts').textContent=counts.forecasts ?? '—';$('outcomes').textContent=`${counts.outcomes ?? 0} matured / ${(counts.forecasts||0)-(counts.outcomes||0)} pending · model test`;
    const warnings=[];
    if(fresh.stale)warnings.push(fresh.active?'The session heartbeat is stale. These are recorded results, not a live market view.':'This session is no longer updating. Results below are a historical snapshot.');
    if(quote?.stale)warnings.push(`The displayed quote was observed at ${date(quote.observed_at_utc)} local.`);
    if(!session.session_id)warnings.push('No paper session is available. Start a local test to populate this desk.');
    $('alert').hidden=!warnings.length;$('alert').textContent=warnings.join(' ');
    renderForecasts(committee);renderPerformance(performance);renderDecisions(decisions);renderNews(news);
    if(regime.regime)$('shadow-note').textContent+=` Recorded context: ${regime.regime.replaceAll('_',' ')} at ${date(regime.source_anchor_utc)} local (one-time snapshot; fixed thresholds; conditional weights disabled).`;
    $('risk-status').textContent=risk.decision ? `${risk.decision.allowed?'ELIGIBLE':'HOLD'} · ${(risk.decision.reasons || []).map(x=>x.replaceAll('_',' ')).join('; ') || 'No blocking reasons'}` : 'Review unavailable; execution disconnected';
  } catch(error) {if(request!==generation)return;$('alert').hidden=false;$('alert').textContent='The local API is unavailable. Displayed values are from the last successful refresh and may be stale.';$('clock').textContent='CONNECTION INTERRUPTED';console.error(error);}
}
async function showAutopsy(id) {
  $('autopsy-title').textContent=`Decision #${id}`;$('autopsy-content').textContent='Reading the evidence…';$('autopsy').showModal();
  try{const data=await get(`/api/v1/decisions/${id}/autopsy?mode=${mode}`),d=data.decision,p=data.position;
    const fields=[['Action',d.action],['Policy',policyName(d.policy)],['Reason',d.reason.replaceAll('_',' ')],['Observed at',new Date(d.time_utc).toLocaleString()],['Expected net return',d.expected_net_return==null?'Not used · forced entry':`${num(d.expected_net_return*10000)} bp`],['Observed bid / ask',d.quote?`${num(d.quote.bid)} / ${num(d.quote.ask)}`:'Unavailable']];
    if(p)fields.push(['Quantity',`${num(p.quantity,8)} BTC`],['Assumed entry fill',`${num(p.entry_price)} USDT`],['Assumed exit fill',p.exit_price?`${num(p.exit_price)} USDT`:'Position open'],['Actual holding duration',p.exit_utc?`${num((new Date(p.exit_utc)-new Date(p.entry_utc))/1000,1)} seconds`:'Pending exit'],['Entry fee assumed',`${num(p.entry_fee_usdt_assumed,6)} USDT`],['Exit fee assumed',p.exit_fee_usdt_assumed==null?'Pending':`${num(p.exit_fee_usdt_assumed,6)} USDT`],['Net paper P&L',p.net_pnl==null?'Unrealized':`${signed(p.net_pnl,6)} USDT`],['Entry receipt SHA-256',p.entry_quote?.receipt_sha256 || 'Unavailable']);
    $('autopsy-content').innerHTML=`<dl class="autopsy-grid">${fields.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl><p class="autopsy-receipt">${esc(data.execution)} Fee ${esc(data.cost_assumptions.fee_bps_per_side_assumed)} bp / side; slippage ${esc(data.cost_assumptions.slippage_bps_per_side_assumed)} bp / side. ${p?'':'This decision did not open a paper position.'}</p>`;
  }catch{$('autopsy-content').textContent='This decision could not be read. Try refreshing the desk.';}
}
$('close-autopsy').onclick=()=>$('autopsy').close();
$('autopsy').addEventListener('click',e=>{if(e.target===$('autopsy')){const r=$('autopsy').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('autopsy').close();}});
document.querySelectorAll('[data-mode]').forEach(button=>button.onclick=()=>{mode=button.dataset.mode;document.querySelectorAll('[data-mode]').forEach(b=>{b.classList.toggle('selected',b===button);b.setAttribute('aria-pressed',b===button?'true':'false');});refresh();});
document.querySelectorAll('section').forEach((el,i)=>{el.classList.add('reveal');el.style.animationDelay=`${Math.min(i*50,250)}ms`;});
refresh();setInterval(refresh,10000);

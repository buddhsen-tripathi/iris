import {useQuery} from '@tanstack/react-query';
import {ArrowUp,Check,ExternalLink,FileText,LoaderCircle,MessageSquare,Square,SquarePen,X} from 'lucide-react';
import {useEffect,useRef,useState} from 'react';
import Markdown from 'react-markdown';
import {askGraph,graphAgentConfigSchema,type GraphAgentEvent,type GraphAnswer,type GraphChatTurn} from '@/lib/graph-agent';
import {safeSourceURL,type NetworkNode,type NetworkResponse} from '@/lib/knowledge';
import {StockPerformance} from './StockPerformance';
import {PeopleResearch} from './PeopleResearch';

const LABELS:Record<string,string>={search_companies:'Resolving companies and tickers',get_connections:'Checking relationship evidence',search_source_evidence:'Searching report passages',find_research_candidates:'Finding source-backed research candidates',research_company_people:'Researching professional backgrounds with Exa',present_research_answer:'Validating citations and company identities'};
type Turn={id:string;role:'user'|'assistant';text?:string;answer?:GraphAnswer;progress:string[];error?:string;state:'working'|'done'|'stopped';cached?:boolean;cost?:number};
function Answer({answer,onSelect}:{answer:GraphAnswer;onSelect:(id:string)=>void}){
  const byId=new Map(answer.citations.map(source=>[source.id,source]));
  const text=answer.answer.replace(/\[(E\d+)\]/g,(match,id:string)=>{const source=byId.get(id);return source?`[${id}](<${source.url}>)`:match;});
  const urls=new Set(answer.citations.map(source=>source.url));
  return <>
    <div className="graph-analyst-markdown"><Markdown components={{a:({href,children})=>href&&urls.has(href)&&safeSourceURL(href)?<a href={href} target="_blank" rel="noreferrer">{children}</a>:<span>{children}</span>}}>{text}</Markdown></div>
    <PeopleResearch people={answer.people} citations={answer.citations} onSelect={onSelect}/>
    {answer.suggestions.length>0&&<section className="graph-stock-shortlist"><h4>Stock research shortlist</h4><p>Source-backed hypotheses to investigate.</p>{answer.suggestions.map(stock=><article key={stock.company_id}><div><strong>{stock.tickers.join(' / ')}</strong><span>{stock.name}</span></div><StockPerformance symbols={stock.tickers}/><p>{stock.hypothesis}</p><ul>{stock.risks.map((risk,i)=><li key={i}>{risk}</li>)}</ul><span className="kicker">Evidence: {stock.evidence_ids.join(', ')}</span><button onClick={()=>onSelect(stock.company_id)}>View company in graph<MessageSquare size={12}/></button></article>)}</section>}
    {answer.citations.length>0&&<details className="graph-answer-sources"><summary><FileText size={13}/>{answer.citations.length} cited sources</summary>{answer.citations.map(source=>{const url=safeSourceURL(source.url);return <article key={source.id}><div><strong>{source.id}</strong><span className={`graph-status graph-status-${source.status==='passage'||source.status==='web'?'reference':source.status}`}>{source.status==='passage'?'Source passage':source.status==='web'?'Web research':source.status}</span></div><h5>{source.title}</h5><p>{source.quote.slice(0,400)}{source.quote.length>400?'…':''}</p>{source.status==='web'&&<p>Retrieved {new Date(source.observed_at).toLocaleString()} · {source.published_at?`Published ${new Date(source.published_at).toLocaleDateString()}`:'Publication date unknown'}</p>}{url&&<a href={url} target="_blank" rel="noreferrer">Read source{source.page?` · Page ${source.page}`:''}<ExternalLink size={11}/></a>}</article>;})}</details>}
    <details className="graph-answer-limits"><summary>Limits &amp; missing checks</summary><ul>{answer.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul></details>
  </>;
}

export function GraphAnalyst({open,onClose,snapshot,selected,onSelect,draftRequest}:{open:boolean;onClose:()=>void;snapshot:NetworkResponse;selected:NetworkNode|undefined;onSelect:(id:string)=>void;draftRequest?:{id:string;question:string}}){
  const [turns,setTurns]=useState<Turn[]>([]),[draft,setDraft]=useState('');
  const abort=useRef<AbortController|null>(null),scroller=useRef<HTMLDivElement>(null),input=useRef<HTMLTextAreaElement>(null);
  const busy=turns.some(turn=>turn.state==='working');
  const config=useQuery({queryKey:['graph-agent-config'],queryFn:async({signal})=>{const response=await fetch('/graph-agent/config',{signal});if(!response.ok)throw new Error('Graph analyst is unavailable');return graphAgentConfigSchema.parse(await response.json());},enabled:open,staleTime:300000,retry:1});
  useEffect(()=>{if(!open)abort.current?.abort();else input.current?.focus();},[open]);
  useEffect(()=>{if(open&&draftRequest)setDraft(draftRequest.question);},[open,draftRequest]);
  useEffect(()=>()=>abort.current?.abort(),[]);
  useEffect(()=>{scroller.current?.scrollTo({top:scroller.current.scrollHeight});},[turns]);
  useEffect(()=>{if(!open)return;const close=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose();};window.addEventListener('keydown',close);return()=>window.removeEventListener('keydown',close);},[open,onClose]);
  function update(id:string,change:(turn:Turn)=>Turn){setTurns(current=>current.map(turn=>turn.id===id?change(turn):turn));}
  async function ask(question:string){
    const text=question.trim();if(!text||busy||!config.data?.enabled||!snapshot.snapshot_id)return;
    const history:GraphChatTurn[]=turns.flatMap(turn=>{
      const content=turn.role==='user'?turn.text:turn.answer?.answer;
      return content?[{role:turn.role,content}]:[];
    });
    if(history.at(-1)?.role==='user')history.pop();
    history.push({role:'user',content:text});
    const id=crypto.randomUUID(),controller=new AbortController();abort.current=controller;
    setDraft('');setTurns(current=>[...current,{id:crypto.randomUUID(),role:'user',text,progress:[],state:'done'},{id,role:'assistant',progress:[],state:'working'}]);
    const consume=(event:GraphAgentEvent)=>update(id,turn=>{
      switch(event.type){
        case 'progress':return {...turn,progress:[...new Set([...turn.progress,LABELS[event.name]??event.name])]};
        case 'answer':return {...turn,answer:event.data,cached:event.cached};
        case 'usage':return {...turn,cost:event.cost};
        case 'error':return {...turn,error:event.message};
        case 'done':return {...turn,state:'done'};
      }
    });
    try{await askGraph({messages:history.slice(-11),snapshot_id:snapshot.snapshot_id,as_of:snapshot.as_of,selected_entity:selected?.id},controller.signal,consume);update(id,turn=>({...turn,state:'done'}));}
    catch(error){update(id,turn=>({...turn,state:controller.signal.aborted?'stopped':'done',error:controller.signal.aborted?undefined:error instanceof Error?error.message:'Graph research failed'}));}
    finally{abort.current=null;}
  }
  if(!open)return null;
  return <aside className="graph-analyst-drawer" role="dialog" aria-label="Ask the graph" aria-modal="false">
    <header><div><h2>Ask the graph</h2><p>Evidence-led questions &amp; stock research</p></div><button aria-label="New graph conversation" disabled={busy} onClick={()=>setTurns([])}><SquarePen size={15}/></button><button aria-label="Close graph analyst" onClick={onClose}><X size={17}/></button></header>
    <div className="graph-analyst-context"><span>Saved graph · {new Date(snapshot.as_of).toLocaleDateString()}</span><span>{selected?selected.name:'All companies'}</span></div>
    <div className="graph-analyst-scroll" ref={scroller} aria-live="polite">
      {config.isError&&<p role="alert">The graph analyst is unavailable. The saved graph is still searchable.</p>}
      {config.data&&!config.data.enabled&&<p role="alert">Graph questions aren't available right now.</p>}
      {!snapshot.snapshot_id&&<p>Refresh data once to enable this graph snapshot for research.</p>}
      {config.data?.peopleResearch&&<p className="graph-people-availability">Exa people research available · Public professional sources</p>}
      {!turns.length&&<div className="graph-analyst-welcome"><MessageSquare size={28}/><h3>Ask why companies connect.</h3><p>Trace a relationship, investigate an industry, or build a stock research shortlist with cited sources.</p>{[
        selected?`Explain ${selected.name}'s reported business relationships with sources.`:'Which listed companies have reported business links to NVIDIA?',
        'Suggest up to three AI infrastructure stocks to research. Cite the evidence and explain the risks.',
        ...(config.data?.peopleResearch?[`Research up to three key people at ${selected?.kind==='company'?selected.name:'NVIDIA'} and their professional backgrounds. Cite company roles, previous experience and education where supported; distinguish former roles and unknown dates.`]:['Which companies mention copper exposure, and what would need checking before investing?']),
      ].map(text=><button key={text} disabled={!config.data?.enabled} onClick={()=>void ask(text)}>{text}<ArrowUp size={12}/></button>)}</div>}
      {turns.map(turn=>turn.role==='user'?<div className="graph-analyst-user" key={turn.id}>{turn.text}</div>:<section className="graph-analyst-turn" key={turn.id}>
        {turn.progress.length>0&&<details className="graph-analyst-progress"><summary>{turn.state==='working'?<LoaderCircle className="animate-spin" size={12}/>:<Check size={12}/>} {turn.state==='working'?'Researching evidence…':turn.answer?'Sources retrieved':'Research steps'}</summary><ul>{turn.progress.map(step=><li key={step}>{step}</li>)}</ul></details>}
        {turn.answer&&<Answer answer={turn.answer} onSelect={onSelect}/>}
        {turn.state==='working'&&!turn.progress.length&&<p className="graph-muted-message">Connecting to graph research…</p>}
        {turn.error&&<p className="graph-analyst-error" role="alert">{turn.error}</p>}
        {turn.state==='stopped'&&<p className="kicker">Stopped</p>}
        {turn.answer&&<p className="graph-analyst-answer-meta">{turn.cached?'Saved answer · ':''}{new Date(turn.answer.generated_at).toLocaleTimeString()}</p>}
      </section>)}
    </div>
    <form className="graph-analyst-form" onSubmit={event=>{event.preventDefault();void ask(draft);}}><div><textarea ref={input} aria-label="Question for graph analyst" value={draft} onChange={event=>setDraft(event.target.value)} maxLength={6000} rows={2} placeholder="Ask a question or suggest a research theme…" onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();void ask(draft);}}}/>{busy?<button type="button" aria-label="Stop graph research" onClick={()=>abort.current?.abort()}><Square size={14}/></button>:<button type="submit" aria-label="Send graph question" disabled={!draft.trim()||!config.data?.enabled||!snapshot.snapshot_id}><ArrowUp size={16}/></button>}</div><p>Graph answers use collected sources; people research uses cited public web pages. Charts fetch market history separately.</p></form>
  </aside>;
}

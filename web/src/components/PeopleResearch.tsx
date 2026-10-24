import {ExternalLink,Users} from 'lucide-react';
import type {GraphAnswer} from '@/lib/graph-agent';
import {safeSourceURL} from '@/lib/knowledge';

const TOPICS={company_role:'Company role',past_role:'Previous experience',education:'Education',research:'Research',other:'Professional background'};
const AFFILIATIONS={current_reported:'Role reported as current',former_reported:'Former role reported',unclear:'Role dates unclear'};
export function PeopleResearch({people,citations,onSelect}:{people:GraphAnswer['people'];citations:GraphAnswer['citations'];onSelect:(id:string)=>void}){
  if(!people.length)return null;
  const sources=new Map(citations.map(source=>[source.id,source]));
  return <section className="graph-people-research" aria-label="People research">
    <h4><Users size={14}/>People &amp; professional backgrounds</h4>
    <p>Source-reported research leads. Check identity and role dates before relying on a connection.</p>
    {people.map(person=><article key={person.id}>
      <header><h5>{person.name}</h5><span>Research lead</span></header>
      <button className="graph-person-company" onClick={()=>onSelect(person.company_id)}>{person.company_name}</button>
      <p className="graph-person-affiliation">{AFFILIATIONS[person.affiliation]}</p>
      {person.claims.map((claim,i)=>{
        const source=sources.get(claim.evidence_id),url=source?safeSourceURL(source.url):null;
        return <div className="graph-person-claim" key={i}>
          <span>{TOPICS[claim.topic]}</span><p>{claim.text}</p>
          <details><summary>Evidence {claim.evidence_id}</summary><blockquote>{claim.quote}</blockquote>{source&&<p>Retrieved {new Date(source.observed_at).toLocaleString()} · {source.published_at?`Published ${new Date(source.published_at).toLocaleDateString()}`:'Publication date unknown'}</p>}{url&&<a href={url} target="_blank" rel="noreferrer">{source?.title}<ExternalLink size={11}/></a>}</details>
        </div>;
      })}
      <p className="graph-person-identity">{person.identity_note}</p>
    </article>)}
    <p>These profiles are separate from the saved relationship graph.</p>
  </section>;
}

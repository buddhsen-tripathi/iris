import {z} from 'zod';
import {answerPersonSchema,researchPersonSchema} from './people-research';

export const graphCitationSchema=z.object({
  id:z.string().regex(/^E\d+$/),source_id:z.string(),title:z.string(),url:z.string().url(),
  quote:z.string(),status:z.enum(['reported','reference','candidate','passage','web']),
  page:z.number().nullable(),entity_ids:z.array(z.string()),observed_at:z.string(),
  published_at:z.string().nullable().optional(),
});
export const researchDraftSchema=z.object({
  answer:z.string().min(1).max(12000).describe('Concise answer. Cite retrieved evidence inline as [E1], [E2]. No raw URLs.'),
  citation_ids:z.array(z.string().regex(/^E\d+$/)).max(24),
  suggestions:z.array(z.object({
    company_id:z.string().max(300),hypothesis:z.string().min(1).max(1400),
    risks:z.array(z.string().max(500)).min(1).max(5),evidence_ids:z.array(z.string().regex(/^E\d+$/)).min(1).max(6),
  })).max(6).describe('Optional source-backed stock research shortlist; these are hypotheses, not trade instructions or return predictions.'),
  people:z.array(researchPersonSchema).max(6).default([]).describe('Optional professional profiles from Exa evidence; source-reported research leads, not accepted graph facts.'),
  limitations:z.array(z.string().max(700)).min(1).max(8),
});
export const graphAnswerSchema=z.object({
  answer:z.string(),citations:z.array(graphCitationSchema),
  suggestions:z.array(z.object({company_id:z.string(),name:z.string(),tickers:z.array(z.string()),
    hypothesis:z.string(),risks:z.array(z.string()),evidence_ids:z.array(z.string())})),
  people:z.array(answerPersonSchema).default([]),
  limitations:z.array(z.string()),as_of:z.string(),snapshot_id:z.string(),generated_at:z.string(),model:z.string(),
});
export type GraphAnswer=z.infer<typeof graphAnswerSchema>;
export type GraphCitation=z.infer<typeof graphCitationSchema>;
export const graphAgentEventSchema=z.discriminatedUnion('type',[
  z.object({type:z.literal('progress'),name:z.string()}),
  z.object({type:z.literal('answer'),data:graphAnswerSchema,cached:z.boolean()}),
  z.object({type:z.literal('usage'),modelCalls:z.number(),cost:z.number().optional()}),
  z.object({type:z.literal('error'),message:z.string()}),
  z.object({type:z.literal('done')}),
]);
export type GraphAgentEvent=z.infer<typeof graphAgentEventSchema>;
export const graphAgentConfigSchema=z.object({enabled:z.boolean(),model:z.string(),maxSteps:z.number(),maxCostUsd:z.number(),peopleResearch:z.boolean().default(false),maxPeopleSearches:z.number().default(0)});
export type GraphChatTurn={role:'user'|'assistant';content:string};

export async function askGraph(body:{messages:GraphChatTurn[];snapshot_id:string;as_of:string;selected_entity?:string},signal:AbortSignal,onEvent:(event:GraphAgentEvent)=>void){
  const response=await fetch('/graph-agent/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});
  if(!response.ok||!response.body){const error=z.object({message:z.string()}).safeParse(await response.json());throw new Error(error.success?error.data.message:'Graph analyst is unavailable');}
  const reader=response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer='';
  try{
    for(;;){
      const {done,value}=await reader.read();
      if(done)break;
      buffer+=value;
      if(buffer.length>150000)throw new Error('Graph analyst response exceeded limits');
      let newline:number;
      while((newline=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,newline).trim();buffer=buffer.slice(newline+1);if(line)onEvent(graphAgentEventSchema.parse(JSON.parse(line)));}
    }
    if(buffer.trim())onEvent(graphAgentEventSchema.parse(JSON.parse(buffer)));
  }finally{reader.releaseLock();}
}

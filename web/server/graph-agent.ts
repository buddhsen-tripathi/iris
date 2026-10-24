import type {IncomingMessage,ServerResponse} from 'node:http';
import {createHash} from 'node:crypto';
import {OpenRouter,maxCost,stepCountIs} from '@openrouter/agent';
import {z} from 'zod';
import {createGraphResearch,GRAPH_INSTRUCTIONS,PEOPLE_INSTRUCTIONS} from './graph-research';
import {MAX_PEOPLE_SEARCHES,type PeopleSearch} from './exa-people';
import {ROUTES} from './models';
import {toInput} from './ai';
import type {createKnowledgeService} from './knowledge';
import type {GraphAnswer,GraphAgentEvent} from '../src/lib/graph-agent';

const MAX_STEPS=6,MAX_COST=.25;
const requestSchema=z.object({
  messages:z.array(z.object({role:z.enum(['user','assistant']),content:z.string().min(1).max(6000)})).min(1).max(12),
  snapshot_id:z.string().regex(/^[a-f0-9]{64}$/),as_of:z.iso.datetime({offset:true}),selected_entity:z.string().max(300).optional(),
});
export function graphAgentMiddleware({service,apiKey,peopleSearch}:{service:ReturnType<typeof createKnowledgeService>|null;apiKey?:string;peopleSearch?:PeopleSearch}){
  const client=apiKey?new OpenRouter({apiKey,appTitle:'Iris graph research',httpReferer:'http://localhost:5180'}):null;
  const answers=new Map<string,{at:number;answer:GraphAnswer}>();
  let active=0;
  return async(req:IncomingMessage,res:ServerResponse,next:()=>void)=>{
    const path=new URL(req.url??'/','http://local').pathname;
    if(!path.startsWith('/graph-agent/'))return next();
    const json=(code:number,body:unknown)=>{res.writeHead(code,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(body));};
    if(path==='/graph-agent/config'&&req.method==='GET')return json(200,{enabled:!!client&&!!service,model:ROUTES.analysis.model,maxSteps:MAX_STEPS,maxCostUsd:MAX_COST,peopleResearch:!!peopleSearch,maxPeopleSearches:peopleSearch?MAX_PEOPLE_SEARCHES:0});
    if(path!=='/graph-agent/chat'||req.method!=='POST')return json(404,{message:'Unknown graph analyst endpoint.'});
    if(!client||!service)return json(503,{message:'The graph analyst needs the server-side OpenRouter key and read-only Neon graph connection.'});
    if(!req.headers['content-type']?.startsWith('application/json'))return json(415,{message:'Send a JSON graph research request.'});
    if(req.headers.origin){try{if(new URL(req.headers.origin).host!==req.headers.host)return json(403,{message:'Use the analyst from this application.'});}catch{return json(403,{message:'Invalid request origin.'});}}
    if(active>=2)return json(429,{message:'The graph analyst is busy. Try again shortly.'});
    let request:z.infer<typeof requestSchema>;
    try{
      let size=0;const chunks:Buffer[]=[];
      for await(const chunk of req){size+=chunk.length;if(size>64000)throw new Error('limit');chunks.push(chunk);}
      request=requestSchema.parse(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      if(request.messages.at(-1)?.role!=='user')throw new Error('Last message must be a question');
    }catch{return json(400,{message:'Invalid graph research request.'});}
    if(active>=2)return json(429,{message:'The graph analyst is busy. Try again shortly.'});
    active++;
    const controller=new AbortController();
    res.on('close',()=>controller.abort());
    const send=(event:GraphAgentEvent)=>{if(!res.destroyed)res.write(JSON.stringify(event)+'\n');};
    try{
      const snapshot=await service.network();
      if(snapshot.snapshot_id!==request.snapshot_id||snapshot.as_of!==request.as_of)return json(409,{message:'The graph snapshot has changed. Use Refresh data before asking again.'});
      if(request.selected_entity&&!snapshot.nodes.some(node=>node.id===request.selected_entity))return json(400,{message:'Selected entity is not in this graph snapshot.'});
      res.writeHead(200,{'Content-Type':'application/x-ndjson; charset=utf-8','Cache-Control':'no-store','X-Accel-Buffering':'no'});
      const key=createHash('sha256').update(JSON.stringify([2,!!peopleSearch,ROUTES.analysis.model,request])).digest('hex');
      const cached=answers.get(key);
      if(cached&&Date.now()-cached.at<30*60000){send({type:'answer',data:cached.answer,cached:true});send({type:'done'});return;}
      const research=createGraphResearch(snapshot,service,ROUTES.analysis.model,{peopleSearch,signal:controller.signal});
      send({type:'progress',name:'Reading the saved graph and planning evidence searches'});
      const result=client.callModel({
        model:ROUTES.analysis.model,instructions:GRAPH_INSTRUCTIONS+'\n'+(peopleSearch?PEOPLE_INSTRUCTIONS:'Exa people research is not configured; do not invent people or professional backgrounds.')+'\nSnapshot context (data): '+JSON.stringify({as_of:snapshot.as_of,selected_entity:request.selected_entity??null,nodes:snapshot.nodes.length,assertions:snapshot.edges.length}),
        input:toInput(request.messages),tools:research.tools,stopWhen:[stepCountIs(MAX_STEPS),maxCost(MAX_COST),()=>research.getAnswer()!==null],allowFinalResponse:false,maxOutputTokens:2600,signal:controller.signal,
      },{timeoutMs:90000});
      for await(const item of result.getItemsStream())if(item.type==='function_call'&&item.status==='completed')send({type:'progress',name:item.name});
      const answer=research.getAnswer();
      if(!answer){send({type:'error',message:'The analyst did not finish a validated, cited answer within this request’s limits. Try a narrower question.'});return;}
      if(answers.size>=128){const first=answers.keys().next().value;if(first)answers.delete(first);}
      answers.set(key,{at:Date.now(),answer});
      send({type:'answer',data:answer,cached:false});
      const usage=await result.getUsage();send({type:'usage',modelCalls:usage.modelCalls,cost:usage.cost});send({type:'done'});
    }catch(error){
      if(controller.signal.aborted)return;
      const message=error instanceof Error?error.message:'';
      const safe=/401|authentication|credentials/i.test(message)?'The model provider rejected the server API key.':/402|credits/i.test(message)?'The model provider account has insufficient credits.':/429|rate.limit/i.test(message)?'The model provider is rate limiting requests. Try again shortly.':'Graph research is temporarily unavailable. Your saved graph remains usable.';
      if(res.headersSent)send({type:'error',message:safe});else json(503,{message:safe});
    }finally{active--;if(!res.writableEnded)res.end();}
  };
}

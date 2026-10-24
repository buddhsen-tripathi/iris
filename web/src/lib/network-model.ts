import type { NetworkEdge, NetworkNode, NetworkResponse } from './knowledge';

export const NODE_COLORS: Record<string,string> = {
  company:'#368778', security:'#78929c', legal_entity:'#9885ad',
  commodity:'#d28342', product:'#ae8449', industry:'#5974a3',
};
export const EDGE_COLORS = {reported:'#27765f',reference:'#adb8ba',candidate:'#cb9d64'};
export const KIND_LABELS: Record<string,string> = {
  company:'Company', security:'Security',legal_entity:'Legal entity',commodity:'Commodity',product:'Product',industry:'Industry',
};
export type NetworkNodeAttributes = {x:number;y:number;label:string;size:number;color:string;kind:string};
export type NetworkEdgeAttributes = {label:string;size:number;color:string;status:NetworkEdge['status'];weight?:number};

export function indexNetwork(data:NetworkResponse) {
  const nodes=new Map(data.nodes.map(node=>[node.id,node]));
  const adjacent=new Map<string,NetworkEdge[]>();
  const tickers=new Map<string,string[]>();
  const append=(id:string,edge:NetworkEdge)=>{
    const list=adjacent.get(id);
    if(list)list.push(edge);else adjacent.set(id,[edge]);
  };
  for(const edge of data.edges) {
    append(edge.subject_id,edge);
    if(edge.object_id!==edge.subject_id)append(edge.object_id,edge);
    if(edge.predicate==='ISSUED_BY'&&edge.status==='reference') {
      const ticker=nodes.get(edge.subject_id)?.ticker;
      if(ticker)tickers.set(edge.object_id,[...(tickers.get(edge.object_id)??[]),ticker]);
    }
  }
  const search=data.nodes.map(node=>({node,tickers:node.ticker?[node.ticker]:(tickers.get(node.id)??[]),
    text:[node.name,...node.aliases,node.ticker??'',...(tickers.get(node.id)??[]),node.id].join(' ').toLowerCase()}));
  return {nodes,adjacent,tickers,search};
}
type NetworkIndex=ReturnType<typeof indexNetwork>;

export function searchNetwork(index:NetworkIndex,query:string,kind='all') {
  const term=query.trim().toLowerCase();
  const tokens=term.split(/\s+/).filter(Boolean);
  return index.search.filter(row=>(kind==='all'||row.node.kind===kind)&&tokens.every(token=>row.text.includes(token)))
    .map(row=>({...row,score:(row.tickers.some(t=>t.toLowerCase()===term)?100:0)+(row.node.name.toLowerCase()===term?90:0)+(row.node.name.toLowerCase().startsWith(term)?20:0)+(row.node.kind==='company'?5:0)}))
    .sort((a,b)=>b.score-a.score||a.node.name.localeCompare(b.node.name)||a.node.id.localeCompare(b.node.id));
}

export type GraphView = 'research' | 'listings' | 'everything';
export const GRAPH_VIEWS: { id: GraphView; label: string; title: string }[] = [
  { id: 'research', label: 'Research', title: 'Reported and candidate business links only' },
  { id: 'listings', label: 'With listings', title: 'Adds listing and ownership references (securities, legal entities)' },
  { id: 'everything', label: 'Everything', title: 'Every collected record, including entities without links' },
];
const STATUS_RANK: Record<NetworkEdge['status'], number> = { reported: 3, candidate: 2, reference: 1 };

/** One drawn link per entity pair: parallel source assertions merge, keeping the strongest status. */
export type MapEdge = NetworkEdge & { count: number };
export type MapNetwork = { nodes: NetworkNode[]; edges: MapEdge[]; degree: Map<string, number> };

/**
 * The map's subset for a view. "research" keeps reported and candidate links and the entities they
 * touch; "listings" adds reference links; "everything" also keeps unlinked entities. With `focus`, only
 * that entity and its direct neighbours remain.
 */
export function mapNetwork(data: NetworkResponse, statuses: Set<NetworkEdge['status']>, view: GraphView, focus: string | null = null): MapNetwork {
  const allowed = (status: NetworkEdge['status']) => statuses.has(status) && (view !== 'research' || status !== 'reference');
  const pairs = new Map<string, MapEdge>();
  for (const edge of data.edges) {
    if (!allowed(edge.status) || edge.subject_id === edge.object_id) continue;
    const key = edge.subject_id < edge.object_id ? `${edge.subject_id}\u0000${edge.object_id}` : `${edge.object_id}\u0000${edge.subject_id}`;
    const existing = pairs.get(key);
    if (!existing) pairs.set(key, { ...edge, count: 1 });
    else {
      existing.count++;
      if (STATUS_RANK[edge.status] > STATUS_RANK[existing.status]) pairs.set(key, { ...edge, count: existing.count });
    }
  }
  let edges = [...pairs.values()];
  if (focus) edges = edges.filter((e) => e.subject_id === focus || e.object_id === focus);
  const degree = new Map<string, number>();
  for (const e of edges) {
    degree.set(e.subject_id, (degree.get(e.subject_id) ?? 0) + 1);
    degree.set(e.object_id, (degree.get(e.object_id) ?? 0) + 1);
  }
  const keep = (id: string) => (focus ? id === focus || degree.has(id) : view === 'everything' || degree.has(id));
  return { nodes: data.nodes.filter((n) => keep(n.id)), edges, degree };
}

/** Distinct research neighbours per entity (reported + candidate), for ranking the directory. */
export function researchDegree(data: NetworkResponse): Map<string, number> {
  const neighbours = new Map<string, Set<string>>();
  for (const e of data.edges) {
    if (e.status === 'reference' || e.subject_id === e.object_id) continue;
    for (const [a, b] of [[e.subject_id, e.object_id], [e.object_id, e.subject_id]]) {
      const set = neighbours.get(a) ?? new Set<string>();
      set.add(b);
      neighbours.set(a, set);
    }
  }
  return new Map([...neighbours].map(([id, set]) => [id, set.size]));
}

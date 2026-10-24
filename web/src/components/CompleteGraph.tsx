import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, Check, ChevronLeft, ChevronRight, ExternalLink, FileText, GitFork, LoaderCircle, MessageSquare, RefreshCw, Search, Users, X } from 'lucide-react';
import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { z } from 'zod';
import { NetworkCanvas, nodeLabel } from './NetworkCanvas';
import { GraphAnalyst } from './GraphAnalyst';
import { Mascot } from './Mascot';
import { Column, DeskGroup, ResizeHandle, Section } from './layout';
import { Panel, Segmented } from './ui';
import { evidenceResponseSchema, graphEdgeSchema, relationLabel, safeSourceURL, type NetworkEdge, type NetworkNode } from '@/lib/knowledge';
import { EDGE_COLORS, GRAPH_VIEWS, KIND_LABELS, NODE_COLORS, indexNetwork, mapNetwork, researchDegree, searchNetwork, type GraphView } from '@/lib/network-model';
import { cn } from '@/lib/utils';
import { GRAPH_CACHE_TTL, loadGraphSnapshot } from '@/lib/graph-cache';

const number = new Intl.NumberFormat('en-US');
const STATUS_LABELS = { reported: 'Reported', reference: 'Reference', candidate: 'Candidate' };
const STATUS_HINTS = {
  reported: 'Publisher-reported business relationships',
  candidate: 'Mentions and name matches: research leads, not confirmed relationships',
  reference: 'Listing and ownership records (securities, legal entities)',
};
const ALL_STATUSES: NetworkEdge['status'][] = ['reported', 'candidate', 'reference'];
const DIRECTORY_SIZE = 40;
const LEDGER_SIZE = 25;

async function readKnowledge(path: string, signal: AbortSignal) {
  const response = await fetch(`/knowledge/${path}`, { signal });
  const data: unknown = await response.json();
  if (!response.ok) {
    const error = z.object({ error: z.string() }).safeParse(data);
    throw new Error(error.success ? error.data.error : 'Graph data is unavailable');
  }
  return data;
}

function Status({ status }: { status: NetworkEdge['status'] }) {
  return (
    <span className={`graph-status graph-status-${status}`}>
      {status === 'reported' && <Check size={10} />} {STATUS_LABELS[status]}
    </span>
  );
}

function Pager({ page, total, size, onPage, label }: { page: number; total: number; size: number; onPage: (page: number) => void; label: string }) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <nav className="flex shrink-0 items-center justify-between gap-3 border-t px-4 py-1.5 text-[10.5px] text-muted-foreground" aria-label={label}>
      <span className="num">
        {total ? `${number.format(page * size + 1)}–${number.format(Math.min((page + 1) * size, total))}` : '0'} of {number.format(total)}
      </span>
      <div className="flex items-center gap-1">
        <button aria-label={`Previous ${label}`} disabled={page === 0} onClick={() => onPage(page - 1)} className="rounded-sm border p-0.5 hover:bg-accent disabled:opacity-40">
          <ChevronLeft size={13} />
        </button>
        <span className="num px-1">
          {page + 1} / {pages}
        </span>
        <button aria-label={`Next ${label}`} disabled={page >= pages - 1} onClick={() => onPage(page + 1)} className="rounded-sm border p-0.5 hover:bg-accent disabled:opacity-40">
          <ChevronRight size={13} />
        </button>
      </div>
    </nav>
  );
}

function CorpusSearch() {
  const [query, setQuery] = useState('');
  const [submitted, setSubmitted] = useState('');
  const results = useQuery({
    queryKey: ['complete-graph-evidence', submitted],
    queryFn: async ({ signal }) => evidenceResponseSchema.parse(await readKnowledge(`search?q=${encodeURIComponent(submitted)}`, signal)),
    enabled: submitted.length >= 2,
    retry: false,
    staleTime: 600000,
  });
  return (
    <div className="px-4 py-3">
      <p className="text-xs leading-relaxed text-muted-foreground">Search collected reports and announcements by meaning and keywords.</p>
      <form
        className="graph-passage-search"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(query.trim());
        }}
      >
        <textarea aria-label="Search evidence corpus" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={600} placeholder="Who supplies packaging and memory for AI systems?" />
        <button disabled={query.trim().length < 2 || results.isFetching}>
          {results.isFetching ? 'Searching…' : 'Search passages'}
          <Search size={13} />
        </button>
      </form>
      {results.isError && <p role="alert" className="text-xs text-down">{results.error.message}</p>}
      {results.data?.warning && <p className="graph-coverage-note">{results.data.warning}</p>}
      {results.data?.passages.map((passage) => {
        const url = safeSourceURL(passage.source_url);
        return (
          <article key={passage.id} className="graph-passage">
            <span className="kicker">
              {passage.matched_by.join(' + ')} · Page {passage.page_number}
            </span>
            <h4>{passage.title}</h4>
            <p>{passage.text.slice(0, 500)}…</p>
            {url && (
              <a href={url} target="_blank" rel="noreferrer">
                Read source
                <ExternalLink size={12} />
              </a>
            )}
          </article>
        );
      })}
      {results.data && !results.data.passages.length && <p className="graph-muted-message">No matching source passages.</p>}
    </div>
  );
}

function KindDot({ kind, className }: { kind: string; className?: string }) {
  return <i className={cn('inline-block size-2 shrink-0 rounded-full', className)} style={{ background: NODE_COLORS[kind] ?? '#789' }} />;
}

export function CompleteGraph({ onClose }: { onClose: () => void; initialSymbol: string }) {
  const refreshRequested = useRef(false);
  const snapshot = useQuery({
    queryKey: ['saved-complete-knowledge-network'],
    queryFn: async ({ signal }) => {
      const force = refreshRequested.current;
      refreshRequested.current = false;
      return loadGraphSnapshot(signal, force);
    },
    staleTime: Infinity,
    gcTime: GRAPH_CACHE_TTL,
    retry: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    networkMode: 'always',
  });
  const data = snapshot.data?.data;
  const refreshGraph = () => {
    refreshRequested.current = true;
    void snapshot.refetch();
  };

  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const deferred = useDeferredValue(query);
  const [directoryPage, setDirectoryPage] = useState(0);
  const [ledgerPage, setLedgerPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [view, setView] = useState<GraphView>('research');
  const [statuses, setStatuses] = useState(new Set(ALL_STATUSES));
  const [focus, setFocus] = useState(false);
  const [reset, setReset] = useState(0);
  const [detailTab, setDetailTab] = useState<'company' | 'corpus'>('company');
  const [analystOpen, setAnalystOpen] = useState(false);
  const [analystDraft,setAnalystDraft]=useState<{id:string;question:string}>();

  const index = useMemo(() => (data ? indexNetwork(data) : null), [data]);
  const ranks = useMemo(() => (data ? researchDegree(data) : new Map<string, number>()), [data]);
  const map = useMemo(() => {
    if (!data || !index) return null;
    const built = mapNetwork(data, statuses, view, focus ? selected : null);
    return { ...built, nodes: built.nodes.map((n) => (n.ticker ? n : { ...n, ticker: index.tickers.get(n.id)?.[0] ?? null })) };
  }, [data, index, statuses, view, focus, selected]);
  const layoutKey = `${data?.snapshot_id ?? data?.as_of}:${view}:${[...statuses].sort().join(',')}:${focus ? selected : ''}`;

  // The directory opens on the most connected entities; typing switches to relevance search.
  const matches = useMemo(() => {
    if (!index) return [];
    if (deferred.trim()) return searchNetwork(index, deferred, kind);
    return index.search
      .filter((row) => kind === 'all' || row.node.kind === kind)
      .sort((a, b) => (ranks.get(b.node.id) ?? 0) - (ranks.get(a.node.id) ?? 0) || (index.adjacent.get(b.node.id)?.length ?? 0) - (index.adjacent.get(a.node.id)?.length ?? 0) || a.node.name.localeCompare(b.node.name));
  }, [index, deferred, kind, ranks]);

  const node = index?.nodes.get(selected ?? '');
  const shownStatuses = (status: NetworkEdge['status']) => statuses.has(status) && (view !== 'research' || status !== 'reference');
  const allLinks = useMemo(() => (data ? (selected ? (index?.adjacent.get(selected) ?? []) : data.edges) : []), [data, selected, index]);
  const links = useMemo(() => allLinks.filter((edge) => shownStatuses(edge.status)), [allLinks, statuses, view]); // eslint-disable-line react-hooks/exhaustive-deps
  const statusCounts = useMemo(() => {
    const counts = { reported: 0, reference: 0, candidate: 0 };
    for (const edge of data?.edges ?? []) counts[edge.status]++;
    return counts;
  }, [data]);
  const counterparties = useMemo(() => {
    if (!selected) return [];
    const rank = { reported: 3, candidate: 2, reference: 1 };
    const groups = new Map<string, { other: string; count: number; edge: NetworkEdge; outgoing: boolean }>();
    for (const item of links) {
      const other = item.subject_id === selected ? item.object_id : item.subject_id;
      const group = groups.get(other);
      if (!group) groups.set(other, { other, count: 1, edge: item, outgoing: item.subject_id === selected });
      else {
        group.count++;
        if (rank[item.status] > rank[group.edge.status]) group.edge = item;
      }
    }
    return [...groups.values()].sort((a, b) => rank[b.edge.status] - rank[a.edge.status] || b.count - a.count);
  }, [links, selected]);
  const hubs = useMemo(() => [...ranks].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([id]) => index?.nodes.get(id)).filter((n): n is NetworkNode => !!n), [ranks, index]);

  const edge = useQuery({
    queryKey: ['complete-graph-link', selectedEdge, data?.as_of],
    queryFn: async ({ signal }) => graphEdgeSchema.parse(await readKnowledge(`link?id=${encodeURIComponent(selectedEdge ?? '')}&as_of=${encodeURIComponent(data?.as_of ?? '')}`, signal)),
    enabled: !!selectedEdge && !!data,
    retry: 1,
    staleTime: 60000,
  });

  useEffect(() => setDirectoryPage(0), [deferred, kind]);
  useEffect(() => setLedgerPage(0), [selected, statuses, view]);
  useEffect(() => {
    const previous = document.title;
    document.title = 'Relationship graph · Iris';
    return () => {
      document.title = previous;
    };
  }, []);

  const selectNode = (id: string) => {
    if (!index?.nodes.has(id)) return;
    setSelected(id);
    setSelectedEdge(null);
    setDetailTab('company');
    // Entities without research links only appear once listings are included.
    if (view === 'research' && !ranks.has(id)) setView('listings');
  };
  const selectEdge = (id: string) => {
    setSelectedEdge(id);
    setDetailTab('company');
  };
  const clearSelection = () => {
    setSelected(null);
    setSelectedEdge(null);
    setFocus(false);
    setReset((v) => v + 1);
  };
  const linkedName = (id: string) => index?.nodes.get(id)?.name ?? id;
  // Short labels use the listing ticker when the entity has none of its own (e.g. NVIDIA → NVDA).
  const shortLabel = (item: NetworkNode) => nodeLabel(item.ticker ? item : { ...item, ticker: index?.tickers.get(item.id)?.[0] ?? null });
  const displayTicker = (item: NetworkNode) => item.ticker ?? index?.tickers.get(item.id)?.join(', ') ?? null;
  const sourceURL = edge.data ? safeSourceURL(edge.data.source_url) : null;
  const searching = deferred !== query;
  const pageMatches = matches.slice(directoryPage * DIRECTORY_SIZE, (directoryPage + 1) * DIRECTORY_SIZE);
  const pageLinks = links.slice(ledgerPage * LEDGER_SIZE, (ledgerPage + 1) * LEDGER_SIZE);

  if (!data)
    return (
      <div className="grid flex-1 place-items-center p-8 text-center text-sm text-muted-foreground">
        {snapshot.isError ? (
          <div className="space-y-3" role="alert">
            <Mascot size={64} mood="cautious" className="mx-auto" />
            <p className="text-foreground">Couldn't load the relationship graph.</p>
            <p className="text-xs">{snapshot.error.message}</p>
            <button onClick={refreshGraph} className="rounded-md border px-3 py-1.5 text-xs hover:bg-accent">
              Try again
            </button>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <Mascot size={72} mood="thinking" />
            <p className="flex items-center gap-2">
              <LoaderCircle className="size-4 animate-spin text-chart-1" /> Loading companies and relationships…
            </p>
          </div>
        )}
      </div>
    );

  const directory = (
    <Panel title="Directory" meta={`${number.format(matches.length)} ${deferred.trim() ? 'matches' : 'entities'}`}>
      <div className="space-y-2 border-b px-3 py-2.5">
        <form
          className="flex items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 focus-within:border-foreground/40"
          onSubmit={(event) => {
            event.preventDefault();
            if (!searching && matches[0]) selectNode(matches[0].node.id);
          }}
        >
          <Search className="size-3.5 text-muted-foreground" />
          <input
            aria-label="Search all companies and entities"
            placeholder="Company, ticker, material…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            maxLength={600}
            className="min-w-0 flex-1 bg-transparent text-[12.5px] outline-none placeholder:text-muted-foreground/70"
          />
          {query && (
            <button type="button" aria-label="Clear company search" onClick={() => setQuery('')} className="text-muted-foreground hover:text-foreground">
              <X size={13} />
            </button>
          )}
        </form>
        <div className="flex items-center justify-between gap-2">
          <span className="kicker">{deferred.trim() ? 'Best matches' : 'Most connected'}</span>
          <select aria-label="Directory entity type" value={kind} onChange={(event) => setKind(event.target.value)} className="rounded-sm border bg-card px-1 py-0.5 text-[11px]">
            <option value="all">All types</option>
            {Object.entries(KIND_LABELS).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <ol className="scroll-thin min-h-0 flex-1 overflow-y-auto py-1">
        {searching ? (
          <li className="px-4 py-6 text-center text-xs text-muted-foreground">Searching…</li>
        ) : (
          pageMatches.map(({ node: item, tickers }) => {
            const research = ranks.get(item.id) ?? 0;
            return (
              <li key={item.id}>
                <button
                  onClick={() => selectNode(item.id)}
                  className={cn(
                    'grid w-full grid-cols-[auto_1fr_auto] items-center gap-x-2.5 border-l-2 px-3 py-1.5 text-left transition-colors',
                    item.id === selected ? 'border-chart-1 bg-accent' : 'border-transparent hover:bg-accent/60',
                  )}
                >
                  <KindDot kind={item.kind} />
                  <span className="min-w-0">
                    <span className="block truncate text-[12.5px] font-medium">{item.name}</span>
                    <span className="block truncate text-[10.5px] text-muted-foreground">
                      {tickers.length ? `${tickers.join(', ')} · ` : ''}
                      {KIND_LABELS[item.kind] ?? item.kind}
                    </span>
                  </span>
                  {research > 0 && (
                    <span className="num rounded-sm bg-muted px-1 text-[10px] text-muted-foreground" title={`${research} research connections`}>
                      {research}
                    </span>
                  )}
                </button>
              </li>
            );
          })
        )}
        {!searching && !matches.length && <li className="px-4 py-6 text-center text-xs text-muted-foreground">No matches. Try NVDA, Microsoft or copper.</li>}
      </ol>
      <Pager page={directoryPage} total={matches.length} size={DIRECTORY_SIZE} onPage={setDirectoryPage} label="directory pages" />
    </Panel>
  );

  const toolbar = (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-2">
      <Segmented label="Graph view" options={GRAPH_VIEWS} value={view} onChange={setView} />
      <div className="flex flex-wrap items-center gap-1.5">
        {ALL_STATUSES.filter((status) => view !== 'research' || status !== 'reference').map((status) => (
          <button
            key={status}
            aria-pressed={statuses.has(status)}
            title={STATUS_HINTS[status]}
            onClick={() =>
              setStatuses((current) => {
                const next = new Set(current);
                if (next.has(status)) next.delete(status);
                else next.add(status);
                return next;
              })
            }
            className={cn(
              'flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] transition-colors',
              statuses.has(status) ? 'bg-card text-foreground' : 'text-muted-foreground line-through opacity-60',
            )}
          >
            <i className="inline-block size-2 rounded-full" style={{ background: EDGE_COLORS[status] }} />
            {STATUS_LABELS[status]}
            <span className="num text-muted-foreground">{number.format(statusCounts[status])}</span>
          </button>
        ))}
      </div>
      {node && (
        <button
          onClick={() => setFocus((value) => !value)}
          aria-pressed={focus}
          className={cn('flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px]', focus ? 'border-chart-1 bg-chart-1/10 text-chart-1' : 'hover:bg-accent')}
        >
          <GitFork size={12} /> {focus ? `Only ${shortLabel(node)}` : `Focus ${shortLabel(node)}`}
        </button>
      )}
      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={refreshGraph}
          disabled={snapshot.isFetching}
          title={snapshot.data ? `Saved ${new Date(snapshot.data.savedAt).toLocaleString()}. Refresh to collect the latest records.` : undefined}
          aria-label="Refresh data"
          className="rounded-md border p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
        >
          <RefreshCw size={13} className={cn(snapshot.isFetching && 'animate-spin')} />
        </button>
        <button onClick={() => setAnalystOpen(true)} className="flex items-center gap-1.5 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:opacity-90">
          <MessageSquare size={13} /> Ask the graph
        </button>
      </div>
    </div>
  );

  const details = (
    <Panel title="Details" meta={node ? KIND_LABELS[node.kind] ?? node.kind : undefined}>
      <div className="flex shrink-0 border-b px-4">
        {(['company', 'corpus'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setDetailTab(tab)}
            className={cn('-mb-px border-b-2 px-1 py-2 text-[11.5px] first:mr-4', detailTab === tab ? 'border-chart-1 text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground')}
          >
            {tab === 'company' ? 'Company & links' : 'Search sources'}
          </button>
        ))}
      </div>
      {detailTab === 'corpus' ? (
        <CorpusSearch />
      ) : selectedEdge ? (
        <div className="px-4 py-3">
          <button className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground" onClick={() => setSelectedEdge(null)}>
            <ArrowLeft size={12} /> {node ? node.name : 'Overview'}
          </button>
          {edge.isFetching && <p className="graph-muted-message">Loading source evidence…</p>}
          {edge.isError && (
            <p className="graph-muted-message" role="alert">
              {edge.error.message}
            </p>
          )}
          {edge.data && (
            <>
              <div className="mt-3">
                <Status status={edge.data.status} />
              </div>
              <h3 className="complete-edge-heading">
                {linkedName(edge.data.subject_id)}
                <span>{relationLabel(edge.data.predicate)}</span>
                {linkedName(edge.data.object_id)}
              </h3>
              {edge.data.evidence_quote ? <blockquote className="complete-quote">{edge.data.evidence_quote}</blockquote> : <p className="graph-muted-message">Reference record. Open the source for details.</p>}
              <div className="graph-source-card">
                <div className="kicker flex items-center gap-1">
                  <FileText size={12} />
                  Source evidence
                </div>
                <strong>{edge.data.title}</strong>
                <p>
                  {edge.data.source_name}
                  {edge.data.page_number ? ` · Page ${edge.data.page_number}` : ''}
                </p>
                {sourceURL && (
                  <a href={sourceURL} target="_blank" rel="noreferrer">
                    Read source <ExternalLink size={12} />
                  </a>
                )}
              </div>
              <dl className="graph-metadata">
                <div>
                  <dt>Observed</dt>
                  <dd>{new Date(edge.data.first_observed_at_utc).toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Published</dt>
                  <dd>{edge.data.published_at_utc ? new Date(edge.data.published_at_utc).toLocaleString() : 'Exact time unknown'}</dd>
                </div>
              </dl>
              <p className="graph-evidence-limit">
                {edge.data.status === 'candidate'
                  ? 'Research lead only. A mention or name match does not establish a commercial relationship.'
                  : edge.data.status === 'reference'
                    ? 'Listing and accounting references are not supply-chain contracts.'
                    : 'A publisher-reported statement; not independently confirmed as a currently active contract. Financial impact is unquantified.'}
              </p>
              <div className="graph-explore-links">
                {[edge.data.subject_id, edge.data.object_id].map((id) => (
                  <button key={id} onClick={() => selectNode(id)}>
                    Explore {linkedName(id)}
                    <ArrowRight size={12} />
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      ) : node ? (
        <div className="px-4 py-3">
          <div className="flex items-start gap-2">
            <KindDot kind={node.kind} className="mt-1.5 size-2.5" />
            <div className="min-w-0">
              <h3 className="text-[15px] leading-snug font-semibold">{node.name}</h3>
              {displayTicker(node) && <p className="num text-[11px] text-muted-foreground">{displayTicker(node)}</p>}
            </div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            {[
              ['Research', ranks.get(node.id) ?? 0],
              ['All links', allLinks.length],
              ['Entities', new Set(allLinks.map((e) => (e.subject_id === selected ? e.object_id : e.subject_id))).size],
            ].map(([label, value]) => (
              <div key={label} className="rounded-md border bg-card/60 px-1 py-1.5">
                <div className="num text-[14px] font-semibold">{number.format(value as number)}</div>
                <div className="kicker">{label}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <button onClick={() => setFocus((value) => !value)} className={cn('flex flex-1 items-center justify-center gap-1.5 rounded-md border px-2 py-1 text-[11.5px]', focus ? 'border-chart-1 text-chart-1' : 'hover:bg-accent')}>
              <GitFork size={12} /> {focus ? 'Show wider graph' : 'Focus connections'}
            </button>
            <button onClick={clearSelection} className="rounded-md border px-2 py-1 text-[11.5px] text-muted-foreground hover:bg-accent hover:text-foreground">
              Clear
            </button>
          </div>
          {node.kind==='company'&&<button className="graph-research-people-button" onClick={()=>{setAnalystDraft({id:crypto.randomUUID(),question:`Research up to three key people professionally connected to ${node.name}. Use Exa to find source-reported company roles and backgrounds: previous employers, education and research where supported. Cite exact evidence, distinguish former roles and unknown dates, and flag identity ambiguity.`});setAnalystOpen(true);}}><Users size={13}/>Research people &amp; backgrounds<ArrowRight size={12}/></button>}
          <h4 className="kicker mt-4 mb-1">Connected to</h4>
          <ol className="divide-y divide-border/60">
            {counterparties.slice(0, 12).map(({ other, count, edge: item, outgoing }) => (
              <li key={other}>
                <button onClick={() => selectEdge(item.id)} className="w-full py-1.5 text-left hover:bg-accent/60" title="Open the strongest source evidence">
                  <span className="flex items-center justify-between gap-2 text-[10.5px] text-muted-foreground">
                    <span className="truncate">
                      {outgoing ? '→' : '←'} {relationLabel(item.predicate)}
                      {count > 1 && <span className="num"> · {number.format(count)} sources</span>}
                    </span>
                    <Status status={item.status} />
                  </span>
                  <span className="flex items-center gap-1.5 text-[12.5px] font-medium">
                    {index?.nodes.get(other) && <KindDot kind={index.nodes.get(other)!.kind} />}
                    <span className="truncate">{linkedName(other)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {!allLinks.length && <p className="graph-muted-message">No relationships collected for this entity yet.</p>}
          {counterparties.length > 12 && <p className="mt-2 text-[11px] text-muted-foreground">{number.format(counterparties.length - 12)} more in the evidence ledger.</p>}
        </div>
      ) : (
        <div className="px-4 py-4">
          <div className="flex items-center gap-3">
            <Mascot size={52} mood="curious" />
            <h3 className="text-[15px] font-semibold">Explore how companies connect</h3>
          </div>
          <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
            Pick an entity on the map or in the directory to see its connections and the source evidence behind each one.
          </p>
          <h4 className="kicker mt-4 mb-1.5">Biggest hubs</h4>
          <div className="grid grid-cols-2 gap-1.5">
            {hubs.map((hub) => (
              <button key={hub.id} onClick={() => selectNode(hub.id)} className="flex items-center gap-1.5 rounded-md border bg-card/60 px-2 py-1.5 text-left text-[11.5px] hover:border-foreground/40 hover:bg-accent">
                <KindDot kind={hub.kind} />
                <span className="truncate">{shortLabel(hub)}</span>
                <span className="num ml-auto text-[10px] text-muted-foreground">{ranks.get(hub.id)}</span>
              </button>
            ))}
          </div>
          <p className="graph-evidence-limit mt-4">Candidate links are research leads from mentions and name matches, not confirmed relationships.</p>
        </div>
      )}
    </Panel>
  );

  return (
    <>
      {snapshot.data?.warning && (
        <p className="graph-coverage-note border-b" role="status">
          {snapshot.data.warning}
        </p>
      )}
      {snapshot.isError && <p className="graph-coverage-note border-b" role="alert">Refresh failed. The saved graph is still available.</p>}
      <DeskGroup id="graph-columns" orientation="horizontal" className="flex-1">
        <Column id="graph-left" defaultSize={290} minSize={220} maxSize={460} fixed className="bg-sidebar/40">
          {directory}
        </Column>
        <ResizeHandle orientation="horizontal" />
        <Column id="graph-main" minSize={460}>
          <DeskGroup id="graph-main" orientation="vertical">
            <Section id="graph-map" defaultSize="64%" minSize={240}>
              <Panel title="Relationship map" meta={map ? `${number.format(map.nodes.length)} entities · ${number.format(map.edges.length)} links` : undefined}>
                {toolbar}
                {map && <NetworkCanvas map={map} layoutKey={layoutKey} selected={selected} onNode={selectNode} onEdge={selectEdge} reset={reset} />}
              </Panel>
            </Section>
            <ResizeHandle orientation="vertical" />
            <Section id="graph-ledger" defaultSize="36%" minSize={120}>
              <Panel title="Evidence ledger" meta={`${node ? `${shortLabel(node)} · ` : ''}${number.format(links.length)} links`} delay={60}>
                <div key={`${selected ?? 'all'}:${ledgerPage}`} className="scroll-thin min-h-0 flex-1 overflow-auto">
                  <table className="w-full table-fixed text-[11.5px]">
                    <colgroup>
                      <col className="w-[31%]" />
                      <col className="w-[22%]" />
                      <col className="w-[27%]" />
                      <col className="w-[10%]" />
                      <col className="w-[10%]" />
                    </colgroup>
                    <thead className="sticky top-0 z-10 bg-background">
                      <tr className="kicker text-left">
                        <th className="px-4 py-1.5 font-semibold">From</th>
                        <th className="px-2 py-1.5 font-semibold">Relationship</th>
                        <th className="px-2 py-1.5 font-semibold">To</th>
                        <th className="px-2 py-1.5 font-semibold">Status</th>
                        <th className="px-4 py-1.5 text-right font-semibold">Evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageLinks.map((item) => (
                        <tr key={item.id} className={cn('border-t border-border/60 hover:bg-accent/50', item.id === selectedEdge && 'bg-accent')}>
                          <td className="truncate px-4 py-1.5">
                            <button onClick={() => selectNode(item.subject_id)} className="max-w-full truncate text-left hover:text-chart-1">
                              {linkedName(item.subject_id)}
                            </button>
                          </td>
                          <td className="truncate px-2 py-1.5 text-muted-foreground">{relationLabel(item.predicate)}</td>
                          <td className="truncate px-2 py-1.5">
                            <button onClick={() => selectNode(item.object_id)} className="max-w-full truncate text-left hover:text-chart-1">
                              {linkedName(item.object_id)}
                            </button>
                          </td>
                          <td className="px-2 py-1.5">
                            <Status status={item.status} />
                          </td>
                          <td className="px-4 py-1.5 text-right">
                            <button onClick={() => selectEdge(item.id)} className="inline-flex items-center gap-1 text-chart-1 hover:underline">
                              Inspect <FileText size={11} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!links.length && <p className="px-4 py-6 text-center text-xs text-muted-foreground">No links match the current selection and filters.</p>}
                </div>
                <Pager page={ledgerPage} total={links.length} size={LEDGER_SIZE} onPage={setLedgerPage} label="relationship pages" />
              </Panel>
            </Section>
          </DeskGroup>
        </Column>
        <ResizeHandle orientation="horizontal" />
        <Column id="graph-right" defaultSize={360} minSize={280} maxSize={560} fixed className="bg-sidebar/40">
          {details}
        </Column>
      </DeskGroup>
      <footer className="flex flex-wrap items-center gap-x-4 border-t px-5 py-1.5 text-[10px] text-muted-foreground">
        <span>Snapshot {new Date(data.as_of).toLocaleString()} · {number.format(data.nodes.length)} entities · {number.format(data.edges.length)} recorded links</span>
        <button onClick={onClose} className="hover:text-foreground">
          ← Back to trading desk
        </button>
        <span className="ml-auto">Company identities are provisional · map positions show link structure, not value</span>
      </footer>
      <GraphAnalyst
        open={analystOpen}
        onClose={() => setAnalystOpen(false)}
        snapshot={data}
        selected={node}
        draftRequest={analystDraft}
        onSelect={(id) => {
          selectNode(id);
          setAnalystOpen(false);
        }}
      />
    </>
  );
}

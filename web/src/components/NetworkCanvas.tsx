import { useEffect, useRef, useState } from 'react';
import Sigma, { DEFAULT_STYLES } from 'sigma';
import { MultiDirectedGraph } from 'graphology';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import FA2Layout from 'graphology-layout-forceatlas2/worker';
import { Maximize, ZoomIn, ZoomOut } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';
import { cssVar } from '@/lib/color';
import { getGraphRecord, setGraphRecord, savedLayoutSchema } from '@/lib/graph-cache';
import { EDGE_COLORS, KIND_LABELS, NODE_COLORS, type MapNetwork, type NetworkEdgeAttributes, type NetworkNodeAttributes } from '@/lib/network-model';
import type { NetworkNode } from '@/lib/knowledge';

type Props = {
  map: MapNetwork;
  /** Identifies this exact node/edge set, for reusing a saved layout of very large views. */
  layoutKey: string;
  selected: string | null;
  onNode: (id: string) => void;
  onEdge: (id: string) => void;
  reset: number;
};

// Above this many nodes the layout runs in a worker and is saved; below it, it's computed instantly.
const SYNC_LAYOUT_LIMIT = 3000;
const GOLDEN = 2.399963229728653;
// Leads and references are many and weak; keep them translucent so hubs and reported links stand out.
const EDGE_ALPHA = { reported: 0.95, candidate: 0.28, reference: 0.22 } as const;
const withAlpha = (hex: string, alpha: number) => {
  const n = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
};

/** Short, readable label: ticker when there is one, else the name without corporate suffixes. */
export function nodeLabel(node: NetworkNode): string {
  if (node.ticker) return node.ticker;
  return node.name.replace(/,?\s+(Inc\.?|Corporation|Corp\.?|Co\.?|Company|Ltd\.?|plc|N\.V\.|S\.A\.|Holdings?|Group)$/i, '').slice(0, 28);
}

function buildGraph(map: MapNetwork) {
  const graph = new MultiDirectedGraph<NetworkNodeAttributes, NetworkEdgeAttributes>();
  // Hubs first, spiralling outward, so the layout starts near its final shape and stays deterministic.
  const nodes = [...map.nodes].sort((a, b) => (map.degree.get(b.id) ?? 0) - (map.degree.get(a.id) ?? 0) || a.id.localeCompare(b.id));
  nodes.forEach((node, i) => {
    const degree = map.degree.get(node.id) ?? 0;
    const radius = 10 * Math.sqrt(i + 1);
    graph.addNode(node.id, {
      x: Math.cos(i * GOLDEN) * radius,
      y: Math.sin(i * GOLDEN) * radius,
      label: nodeLabel(node),
      size: Math.min(18, 2.5 + Math.log2(1 + degree) * 2.2),
      color: NODE_COLORS[node.kind] ?? '#7d8d8a',
      kind: node.kind,
    });
  });
  for (const edge of map.edges) {
    if (!graph.hasNode(edge.subject_id) || !graph.hasNode(edge.object_id)) continue;
    graph.addDirectedEdgeWithKey(edge.id, edge.subject_id, edge.object_id, {
      label: edge.predicate.toLowerCase().replaceAll('_', ' '),
      size: Math.min(4, 0.6 + Math.log2(edge.count) * 0.55) * (edge.status === 'reported' ? 1.6 : 1),
      color: withAlpha(EDGE_COLORS[edge.status], EDGE_ALPHA[edge.status]),
      status: edge.status,
      weight: edge.count,
    });
  }
  return graph;
}

export function NetworkCanvas({ map, layoutKey, selected, onNode, onEdge, reset }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const renderer = useRef<Sigma<NetworkNodeAttributes, NetworkEdgeAttributes> | null>(null);
  const [error, setError] = useState(false);
  const [settling, setSettling] = useState(false);
  const { theme } = useTheme();
  const callbacks = useRef({ onNode, onEdge });
  const view = useRef<{ selected: string | null; hovered: string | null }>({ selected, hovered: null });
  useEffect(() => {
    callbacks.current = { onNode, onEdge };
  }, [onNode, onEdge]);

  useEffect(() => {
    if (!host.current) return;
    const graph = buildGraph(map);
    const large = graph.order > SYNC_LAYOUT_LIMIT;
    if (!large && graph.order > 1) {
      forceAtlas2.assign(graph, {
        iterations: graph.order < 600 ? 600 : 250,
        getEdgeWeight: 'weight',
        settings: { ...forceAtlas2.inferSettings(graph), linLogMode: true, gravity: 1.2, scalingRatio: 4, edgeWeightInfluence: 0.4, barnesHutOptimize: graph.order > 400 },
      });
    }
    const foreground = cssVar('--foreground');
    let sigma: Sigma<NetworkNodeAttributes, NetworkEdgeAttributes>;
    try {
      sigma = new Sigma(graph, host.current, {
        settings: {
          labelDensity: 0.55,
          labelGridCellSize: 110,
          labelRenderedSizeThreshold: large ? 6 : 7,
          enableEdgeEvents: true,
          hideLabelsOnMove: large,
          stagePadding: 40,
          minCameraRatio: 0.01,
          maxCameraRatio: 4,
        },
        styles: { nodes: { ...DEFAULT_STYLES.nodes, labelColor: foreground, labelFont: 'Geist Variable', labelSize: 11 }, edges: { ...DEFAULT_STYLES.edges } },
        nodeReducer: (id, display) => {
          const { selected: chosen, hovered } = view.current;
          const anchor = hovered ?? chosen;
          if (!anchor) return display;
          const near = id === anchor || graph.areNeighbors(id, anchor);
          return {
            ...display,
            color: near ? display.color : cssVar('--muted-foreground', 0.25),
            labelVisibility: id === anchor || (near && (display.size ?? 0) > 3) ? 'visible' : near ? 'auto' : 'hidden',
            size: id === anchor ? Math.max(display.size ?? 4, 8) : display.size,
            zIndex: id === anchor ? 3 : near ? 2 : 0,
          };
        },
        edgeReducer: (id, display) => {
          const { selected: chosen, hovered } = view.current;
          const anchor = hovered ?? chosen;
          if (!anchor) return display;
          const touches = graph.source(id) === anchor || graph.target(id) === anchor;
          const status = graph.getEdgeAttribute(id, 'status');
          return touches ? { ...display, color: EDGE_COLORS[status], zIndex: 1 } : { ...display, visibility: 'hidden' };
        },
      });
    } catch {
      setError(true);
      return;
    }
    renderer.current = sigma;
    sigma.on('clickNode', ({ node }) => callbacks.current.onNode(node));
    sigma.on('clickNodeLabel', ({ node }) => callbacks.current.onNode(node));
    sigma.on('clickEdge', ({ edge }) => callbacks.current.onEdge(edge));
    sigma.on('enterNode', ({ node }) => {
      view.current.hovered = node;
      sigma.refresh({ skipIndexation: true });
      if (host.current) host.current.style.cursor = 'pointer';
    });
    sigma.on('leaveNode', () => {
      view.current.hovered = null;
      sigma.refresh({ skipIndexation: true });
      if (host.current) host.current.style.cursor = '';
    });

    // Very large views: reuse saved positions for this exact set, else settle in a worker once and save.
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let worker: FA2Layout | undefined;
    if (large) {
      const key = `layout:${layoutKey}`;
      void getGraphRecord(key).then((value) => {
        if (cancelled) return;
        const saved = savedLayoutSchema.safeParse(value);
        if (saved.success && saved.data.snapshotId === layoutKey && graph.nodes().every((id) => saved.data.positions[id])) {
          graph.forEachNode((id) => graph.mergeNodeAttributes(id, saved.data.positions[id]));
          sigma.refresh();
          return;
        }
        worker = new FA2Layout(graph, { settings: { barnesHutOptimize: true, barnesHutTheta: 0.7, gravity: 1, scalingRatio: 8, slowDown: 8 } });
        worker.start();
        setSettling(true);
        timer = setTimeout(() => {
          worker?.stop();
          setSettling(false);
          const positions: Record<string, { x: number; y: number }> = {};
          graph.forEachNode((id, attrs) => (positions[id] = { x: attrs.x, y: attrs.y }));
          void setGraphRecord(key, { version: 1, snapshotId: layoutKey, positions });
        }, 4000);
      });
    }
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      worker?.kill();
      setSettling(false);
      sigma.kill();
      renderer.current = null;
    };
  }, [map, layoutKey, theme]);

  // Selection: highlight and frame the selected entity with its neighbours.
  useEffect(() => {
    view.current.selected = selected;
    const sigma = renderer.current;
    if (!sigma) return;
    sigma.refresh({ skipIndexation: true });
    if (!selected) return;
    const graph = sigma.getGraph();
    if (!graph.hasNode(selected)) return;
    const positions = [selected, ...graph.neighbors(selected)].map((id) => sigma.graphToFramedGraph(graph.getNodeAttributes(id)));
    const xs = positions.map((p) => p.x);
    const ys = positions.map((p) => p.y);
    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
    void sigma.getCamera().animate(
      { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2, ratio: Math.min(1, Math.max(0.06, span * 1.6)) },
      { duration: 450 },
    );
  }, [selected, map]);

  useEffect(() => {
    if (reset) void renderer.current?.getCamera().reset({ duration: 350 });
  }, [reset]);

  const kinds = [...new Set(map.nodes.map((n) => n.kind))];
  return (
    <div className="relative min-h-0 flex-1" data-ask-scope="Relationship map">
      <div
        ref={host}
        className="absolute inset-0"
        role="img"
        aria-label={`Relationship map: ${map.nodes.length.toLocaleString()} entities and ${map.edges.length.toLocaleString()} links. Search the directory to select any company.`}
        data-node-count={map.nodes.length}
        data-edge-count={map.edges.length}
      />
      {error && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center text-xs text-muted-foreground" role="alert">
          The map needs WebGL, which isn't available here. Every company and link is still in the directory and ledger.
        </div>
      )}
      {!error && map.nodes.length === 0 && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center text-xs text-muted-foreground">No links match these filters.</div>
      )}
      <div className="pointer-events-none absolute bottom-2 left-3 flex flex-wrap gap-x-3 gap-y-1 rounded-md bg-card/80 px-2 py-1 text-[10px] text-muted-foreground backdrop-blur-sm">
        {kinds.map((kind) => (
          <span key={kind} className="flex items-center gap-1">
            <i className="inline-block size-2 rounded-full" style={{ background: NODE_COLORS[kind] }} />
            {KIND_LABELS[kind] ?? kind}
          </span>
        ))}
        {settling && <span className="text-chart-1">arranging…</span>}
      </div>
      <div className="absolute right-3 bottom-2 flex flex-col overflow-hidden rounded-md border bg-card/90 shadow-xs backdrop-blur-sm">
        <button aria-label="Zoom in" className="p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" onClick={() => void renderer.current?.getCamera().zoomIn({ duration: 200 })}>
          <ZoomIn className="size-3.5" />
        </button>
        <button aria-label="Zoom out" className="border-t p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" onClick={() => void renderer.current?.getCamera().zoomOut({ duration: 200 })}>
          <ZoomOut className="size-3.5" />
        </button>
        <button aria-label="Fit map" className="border-t p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" onClick={() => void renderer.current?.getCamera().reset({ duration: 350 })}>
          <Maximize className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

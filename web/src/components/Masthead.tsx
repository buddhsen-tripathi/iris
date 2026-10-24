import { Film, GitFork, LayoutDashboard, Moon, MousePointerClick, Search, Sparkles, Sun } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Catalog } from "@/hooks/useCatalog";
import { useNow, useSocketStatus } from "@/hooks/useMarket";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import { AssetIcon } from "./ui";

const dateline = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
const clock = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "UTC" });

function SymbolSearch({ catalog, onSelect }: { catalog: Catalog; onSelect: (symbol: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement;
      if ((event.key === "k" && (event.metaKey || event.ctrlKey)) || (event.key === "/" && !typing)) {
        event.preventDefault();
        dialog.current?.showModal();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const results = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return catalog.all.slice(0, 40);
    const exact = catalog.all.filter((a) => a.symbol.toUpperCase().startsWith(q));
    const named = catalog.all.filter((a) => !a.symbol.toUpperCase().startsWith(q) && a.name.toUpperCase().includes(q));
    return [...exact, ...named].slice(0, 40);
  }, [catalog.all, query]);

  const choose = (symbol: string) => {
    onSelect(symbol.toUpperCase());
    dialog.current?.close();
    setQuery("");
  };

  return (
    <>
      <button
        onClick={() => dialog.current?.showModal()}
        className="flex w-64 items-center gap-2 rounded-md border bg-card/70 px-2.5 py-1.5 text-xs text-muted-foreground shadow-2xs hover:text-foreground"
      >
        <Search className="size-3.5" />
        <span className="flex-1 text-left">Search {catalog.all.length || ""} instruments</span>
        <kbd className="num rounded-sm border px-1 text-[10px]">⌘K</kbd>
      </button>
      <dialog
        ref={dialog}
        onClose={() => setQuery("")}
        onClick={(event) => event.target === dialog.current && dialog.current?.close()}
        className="m-auto mt-[12vh] w-[min(560px,92vw)] rounded-xl border bg-popover p-0 text-popover-foreground shadow-2xl backdrop:bg-foreground/20 backdrop:backdrop-blur-[2px]"
      >
        <div className="rule-double flex items-center gap-2 px-4 py-3">
          <Search className="size-4 text-muted-foreground" />
          <input
            autoFocus
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") setCursor((c) => Math.min(results.length - 1, c + 1));
              else if (event.key === "ArrowUp") setCursor((c) => Math.max(0, c - 1));
              else if (event.key === "Enter" && results[cursor]) choose(results[cursor].symbol);
              else return;
              event.preventDefault();
            }}
            placeholder="Symbol or name — BTC, Nvidia, Hyperliquid…"
            className="flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground/70"
          />
        </div>
        <ul className="scroll-thin max-h-[50vh] overflow-y-auto py-1" role="listbox">
          {results.map((asset, index) => (
            <li key={asset.id} role="option" aria-selected={index === cursor}>
              <button
                onMouseEnter={() => setCursor(index)}
                onClick={() => choose(asset.symbol)}
                className={cn("flex w-full items-center gap-3 px-4 py-2 text-left", index === cursor && "bg-accent")}
              >
                <AssetIcon src={asset.icon} symbol={asset.symbol} />
                <span className="w-20 text-[13px] font-semibold">{asset.symbol}</span>
                <span className="flex-1 truncate text-xs text-muted-foreground">{asset.name}</span>
                <span className="kicker">{asset.asset_class === "stock" ? "stock" : (asset.chain ?? asset.venue)}</span>
                {catalog.perps.has(asset.symbol.toUpperCase()) && <span className="kicker text-chart-1">perp</span>}
              </button>
            </li>
          ))}
          {results.length === 0 && <li className="px-4 py-6 text-center text-xs text-muted-foreground">Nothing listed by that name.</li>}
        </ul>
      </dialog>
    </>
  );
}

const STATUS = {
  open: "Live",
  connecting: "Connecting",
  reconnecting: "Reconnecting",
  idle: "Idle",
} as const;

export function Masthead({ catalog, onSelect, onAsk, onGraph, onCreators, onDesk, onPoint, pointing = false, activeView = 'desk' }: { catalog: Catalog; onSelect: (symbol: string) => void; onAsk: () => void; onGraph: () => void; onCreators: () => void; onDesk: () => void; onPoint?: () => void; pointing?: boolean; activeView?: 'desk' | 'creators' | 'graph' }) {
  const { theme, toggle } = useTheme();
  const status = useSocketStatus();
  const now = useNow();
  return (
    <header className="masthead rule-double flex items-center gap-6 px-5 py-2.5">
      <div className="flex items-baseline gap-3">
        <span className="text-lg leading-none font-semibold tracking-tight">
          I<span className="text-chart-1">ris</span>
        </span>
      </div>
      <nav className="desk-page-nav" aria-label="Primary navigation">
        <button aria-current={activeView === 'desk' ? 'page' : undefined} onClick={onDesk}><LayoutDashboard size={13}/> Trading desk</button>
        <button aria-current={activeView === 'creators' ? 'page' : undefined} onClick={onCreators}><Film size={13}/> Creators</button>
      </nav>
      <div className="masthead-date hidden flex-1 justify-center text-[11px] text-muted-foreground xl:flex">
        <span>{dateline.format(now)}</span>
        <span className="mx-2">·</span>
        <span className="num">{clock.format(now)} UTC</span>
      </div>
      <div className="masthead-tools ml-auto flex items-center gap-3">
        <SymbolSearch catalog={catalog} onSelect={onSelect} />
        <button
          onClick={onGraph}
          aria-current={activeView === 'graph' ? 'page' : undefined}
          className={cn("flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium hover:bg-accent", activeView === 'graph' && "border-chart-1 bg-chart-1/10 text-chart-1")}
        >
          <GitFork className="size-3.5" /> Asset graph
        </button>
        {onPoint && (
          <button
            data-ask-ignore
            onClick={onPoint}
            aria-pressed={pointing}
            aria-label="Point & ask"
            className={cn(
              "rounded-md border p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground",
              pointing && "border-chart-1 bg-chart-1/10 text-chart-1 hover:text-chart-1",
            )}
            title="Point & ask: click any element to ask about it (or ⌥-click anywhere)"
          >
            <MousePointerClick className="size-3.5" />
          </button>
        )}
        <button
          onClick={onAsk}
          className="flex items-center gap-1.5 rounded-md bg-primary px-2.5 py-1.5 text-xs font-medium text-primary-foreground shadow-2xs hover:opacity-90"
          title="Ask the desk analyst (⌘J)"
        >
          <Sparkles className="size-3.5" />
          Ask analyst
          <kbd className="num rounded-sm border border-primary-foreground/30 px-1 text-[10px] opacity-80">⌘J</kbd>
        </button>
        <span className="kicker flex items-center gap-1.5" title="Live market data connection">
          <span
            className={cn("size-1.5 rounded-full", status === "open" ? "live-dot bg-chart-1" : "bg-muted-foreground")}
          />
          {STATUS[status]}
        </span>
        <button
          onClick={toggle}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          className="rounded-md border p-1.5 text-muted-foreground hover:text-foreground"
        >
          {theme === "dark" ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
        </button>
      </div>
    </header>
  );
}

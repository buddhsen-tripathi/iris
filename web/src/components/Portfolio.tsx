import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useNow } from "@/hooks/useMarket";
import { age, compact, price, size } from "@/lib/format";
import { trade } from "@/lib/trade";
import { cn } from "@/lib/utils";
import { AssetIcon, Delta, Empty, Panel } from "./ui";

const usd = (v: string | number | undefined) => (v === undefined || !Number.isFinite(Number(v)) ? "—" : `$${price(Number(v), 2)}`);

/** Live True Markets account: total value, holdings and recent orders. Read-only. */
export function Portfolio({ onSelect }: { onSelect: (symbol: string) => void }) {
  const now = useNow(15_000);
  const status = useQuery({ queryKey: ["trade-status"], queryFn: trade.status, refetchInterval: 60_000 });
  const account = useQuery({ queryKey: ["trade-account"], queryFn: trade.account, enabled: status.data?.keyConfigured === true, refetchInterval: 20_000 });

  if (status.data && !status.data.keyConfigured) return <Panel title="Portfolio"><Empty>Connect a True Markets account to see your portfolio.</Empty></Panel>;
  const p = account.data?.portfolio;
  const holdings = (p?.balances ?? []).filter((b) => Number(b.total) > 0).sort((a, b) => Number(b.value ?? 0) - Number(a.value ?? 0));
  const activity = [...(account.data?.orders ?? []), ...(account.data?.transactions ?? [])]
    .filter((row, i, all) => all.findIndex((other) => (other.order_id ?? other.id) === (row.order_id ?? row.id)) === i)
    .sort((a, b) => Date.parse(String(b.created_at ?? "")) - Date.parse(String(a.created_at ?? "")))
    .slice(0, 8);

  return (
    <Panel title="Portfolio" meta={account.data ? `updated ${age(Date.parse(account.data.fetchedAt), now)} ago` : "True Markets"}>
      {account.isError ? (
        <Empty>{account.error.message}</Empty>
      ) : !p ? (
        <Empty>Loading your account…</Empty>
      ) : (
        <>
          <div className="px-4 pt-3 pb-2">
            <div className="kicker">Total value</div>
            <div className="flex items-baseline gap-2">
              <span className="text-[1.6rem] leading-tight font-semibold tabular-nums">{usd(p.total_usd)}</span>
              <Delta value={p.change_24h_pct} className="text-[11px]" />
            </div>
            <div className="num mt-0.5 flex gap-3 text-[10.5px] text-muted-foreground">
              <span>cash {usd(p.cash_usd)}</span>
              {p.unrealized_pnl_usd !== undefined && Number(p.unrealized_pnl_usd) !== 0 && <span>unrealised {usd(p.unrealized_pnl_usd)}</span>}
            </div>
          </div>
          <h3 className="kicker border-t px-4 pt-2 pb-1">Holdings</h3>
          <ul className="pb-1">
            {holdings.map((h) => (
              <li key={h.asset_id}>
                <button
                  onClick={() => !h.stable && onSelect(h.symbol.toUpperCase())}
                  className={cn("grid w-full grid-cols-[auto_1fr_auto] items-center gap-x-2.5 px-4 py-1.5 text-left", !h.stable && "hover:bg-accent/60")}
                >
                  <AssetIcon src={h.icon} symbol={h.symbol} />
                  <span className="min-w-0">
                    <span className="block text-[12.5px] font-semibold">{h.symbol}</span>
                    <span className="num block truncate text-[10.5px] text-muted-foreground">
                      {size(h.total)} {h.chain ? `· ${h.chain}` : ""}
                      {Number(h.available) < Number(h.total) ? ` · ${size(h.available)} free` : ""}
                    </span>
                  </span>
                  <span className="text-right">
                    <span className="num block text-[12px]">{usd(h.value)}</span>
                    {!h.stable && <Delta value={h.change_24h_pct} className="block text-[10px]" />}
                  </span>
                </button>
              </li>
            ))}
            {!holdings.length && <li className="px-4 py-3 text-xs text-muted-foreground">No holdings yet.</li>}
          </ul>
          <h3 className="kicker border-t px-4 pt-2 pb-1">Recent activity</h3>
          <ul className="pb-2">
            {activity.map((row, i) => {
              const status = String(row.status ?? "");
              const explorer = typeof row.explorer_url === "string" && /^https:\/\//.test(row.explorer_url) ? row.explorer_url : null;
              return (
                <li key={String(row.order_id ?? row.id ?? i)} className="num grid grid-cols-[1fr_auto] gap-x-2 px-4 py-1 text-[11px]">
                  <span className="truncate">
                    <span className={cn("font-sans font-semibold capitalize", row.side === "buy" ? "text-up" : row.side === "sell" ? "text-down" : "")}>{String(row.side ?? row.type ?? "activity")}</span>{" "}
                    {String(row.asset_symbol ?? row.symbol ?? "")} {row.executed_qty ? size(String(row.executed_qty)) : row.qty ? size(String(row.qty)) : ""}
                  </span>
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <span className={cn(status === "complete" || status === "completed" ? "text-positive" : status === "failed" ? "text-negative" : "")}>{status}</span>
                    {row.created_at ? <span>{age(Date.parse(String(row.created_at)), now)}</span> : null}
                    {explorer && (
                      <a href={explorer} target="_blank" rel="noreferrer" aria-label="View transaction" className="hover:text-foreground">
                        <ExternalLink className="size-3" />
                      </a>
                    )}
                  </span>
                </li>
              );
            })}
            {!activity.length && <li className="px-4 py-2 text-xs text-muted-foreground">No orders yet. Place one from the trade ticket.</li>}
          </ul>
          <p className="kicker border-t px-4 py-1.5 tracking-normal normal-case">{compact(Number(p.total_usd ?? 0), "$")} across {holdings.length} holding{holdings.length === 1 ? "" : "s"}</p>
        </>
      )}
    </Panel>
  );
}

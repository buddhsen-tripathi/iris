import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ExternalLink, Loader2, Lock, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNow } from "@/hooks/useMarket";
import { price, size } from "@/lib/format";
import { tm, type Asset } from "@/lib/tm";
import { trade, type TradePreview, type TradeResult } from "@/lib/trade";
import { cn } from "@/lib/utils";
import { Empty, Panel, Segmented } from "./ui";

const CHAIN_PREFERENCE = ["solana", "base", "robinhood"];

/** The DeFi spot listing an order for `symbol` would use, preferring chains the wallet commonly funds. */
function pickAsset(assets: Asset[] | undefined, symbol: string) {
  const options = (assets ?? []).filter((a) => a.symbol.toUpperCase() === symbol && a.venue === "defi" && a.type === "spot" && a.tradeable && !a.stable);
  return options.sort((a, b) => rank(a.chain) - rank(b.chain))[0];
}
const rank = (chain: string | null) => {
  const i = CHAIN_PREFERENCE.indexOf(chain ?? "");
  return i < 0 ? 99 : i;
};

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5 text-[12px]">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("num text-right", strong && "font-semibold")}>{value}</span>
    </div>
  );
}

/** Market orders on the selected asset through the True Markets account. Previews are free; confirming moves real funds. */
export function TradeTicket({ symbol }: { symbol: string }) {
  const queryClient = useQueryClient();
  const now = useNow(1000);
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [amount, setAmount] = useState("");
  const [preview, setPreview] = useState<TradePreview | null>(null);
  const [armedUntil, setArmedUntil] = useState(0);
  const [result, setResult] = useState<TradeResult | null>(null);
  const outcome = useRef<HTMLDivElement>(null);
  // Bring the quote (and later the result) into view; the ticket may be shorter than its content.
  useEffect(() => {
    if (preview || result) outcome.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [preview, result]);

  const status = useQuery({ queryKey: ["trade-status"], queryFn: trade.status, refetchInterval: 60_000 });
  const assets = useQuery({ queryKey: ["assets", "spot-crypto"], queryFn: () => tm.assets("spot", "crypto"), staleTime: 10 * 60_000 });
  const account = useQuery({ queryKey: ["trade-account"], queryFn: trade.account, enabled: status.data?.keyConfigured === true, refetchInterval: 20_000 });
  const asset = useMemo(() => pickAsset(assets.data?.data, symbol), [assets.data, symbol]);
  const tradable = useQuery({ queryKey: ["tradable", asset?.id], queryFn: () => trade.tradable(asset!.id), enabled: !!asset && status.data?.keyConfigured === true, staleTime: 10 * 60_000 });
  const holding = account.data?.portfolio.balances?.find((b) => b.asset_id === asset?.id);
  const cash = Number(account.data?.portfolio.cash_usd ?? 0);

  // A new instrument or side starts a fresh ticket.
  useEffect(() => {
    setPreview(null);
    setResult(null);
    setAmount("");
    setArmedUntil(0);
  }, [symbol, side]);

  const previewMutation = useMutation({
    mutationFn: () => trade.preview({ assetId: asset!.id, side, amount }),
    onSuccess: (data) => {
      setPreview(data);
      setResult(null);
      setArmedUntil(0);
    },
  });
  const executeMutation = useMutation({
    mutationFn: (previewId: string) => trade.execute(previewId),
    onSuccess: (data) => {
      setResult(data);
      setPreview(null);
      setAmount("");
      void queryClient.invalidateQueries({ queryKey: ["trade-account"] });
      void queryClient.invalidateQueries({ queryKey: ["trade-status"] });
    },
    onSettled: () => setArmedUntil(0),
  });

  const s = status.data;
  if (s && !s.keyConfigured) return <Panel title="Trade"><Empty>Connect a True Markets account to trade from the desk.</Empty></Panel>;
  const blockedReason = !asset ? `${symbol} has no spot listing your wallet can trade.` : tradable.data?.reason;
  const remaining = preview ? Math.max(0, Math.round((Date.parse(preview.expiresAt) - now) / 1000)) : 0;
  const armed = armedUntil > now;
  const maxBuy = Math.min(s?.maxOrderUsd ?? 10, cash);
  const amountNumber = Number(amount);
  const canPreview = !!asset && !blockedReason && amountNumber > 0 && !previewMutation.isPending;
  const left = s?.dailyLimitUsd !== undefined && s.usedTodayUsd != null ? Math.max(0, s.dailyLimitUsd - s.usedTodayUsd) : undefined;

  const confirm = () => {
    if (!preview || !s?.enabled || remaining === 0) return;
    if (!armed) return setArmedUntil(Date.now() + 6000);
    executeMutation.mutate(preview.previewId);
  };

  return (
    <Panel title="Trade" meta={asset ? `${symbol} · ${asset.chain}` : symbol}>
      <div className="space-y-2.5 px-4 py-3">
        {!s?.enabled && (
          <p className="flex items-start gap-1.5 rounded-md border border-dashed px-2.5 py-1.5 text-[11px] text-muted-foreground">
            <Lock className="mt-0.5 size-3 shrink-0" /> Live orders are switched off on this server. You can still preview quotes.
          </p>
        )}
        {blockedReason ? (
          <p className="text-[12px] text-muted-foreground">{blockedReason} Try SOL or another spot crypto listing.</p>
        ) : (
          <>
            <div className="[&>div]:w-full [&_button]:flex-1">
              <Segmented
                label="Order side"
                options={[
                  { id: "buy", label: `Buy ${symbol}` },
                  { id: "sell", label: `Sell ${symbol}` },
                ]}
                value={side}
                onChange={setSide}
              />
            </div>
            <label className="block">
              <span className="kicker">{side === "buy" ? "Spend (USD)" : `Sell (${symbol})`}</span>
              <div className="mt-1 flex items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 focus-within:border-foreground/40">
                {side === "buy" && <span className="num text-muted-foreground">$</span>}
                <input
                  inputMode="decimal"
                  value={amount}
                  onChange={(e) => {
                    setAmount(e.target.value.replace(/[^\d.]/g, ""));
                    setPreview(null);
                    setArmedUntil(0);
                  }}
                  placeholder={side === "buy" ? "2.00" : "0.01"}
                  aria-label={side === "buy" ? "Amount to spend in dollars" : `Amount of ${symbol} to sell`}
                  className="num min-w-0 flex-1 bg-transparent text-[14px] outline-none"
                />
                {side === "sell" && <span className="num text-[11px] text-muted-foreground">{symbol}</span>}
              </div>
            </label>
            <div className="flex flex-wrap gap-1.5">
              {side === "buy"
                ? [1, 2, 5].filter((v) => v <= maxBuy).map((v) => (
                    <button key={v} onClick={() => (setAmount(String(v)), setPreview(null))} className="num rounded-full border px-2 py-0.5 text-[11px] hover:bg-accent">
                      ${v}
                    </button>
                  ))
                : holding && Number(holding.available) > 0 && (
                    <button onClick={() => (setAmount(holding.available), setPreview(null))} className="num rounded-full border px-2 py-0.5 text-[11px] hover:bg-accent">
                      Max {size(holding.available)}
                    </button>
                  )}
              <span className="num ml-auto self-center text-[10.5px] text-muted-foreground">
                {side === "buy" ? `cash $${price(cash, 2)}` : `holding ${size(holding?.available ?? 0)} ${symbol}`}
              </span>
            </div>
            <button
              onClick={() => previewMutation.mutate()}
              disabled={!canPreview}
              className="flex w-full items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 text-[12.5px] font-medium hover:bg-accent disabled:opacity-40"
            >
              {previewMutation.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
              {preview ? "Refresh quote" : "Preview order"}
            </button>
            {previewMutation.isError && (
              <p className="flex items-start gap-1.5 text-[11.5px] text-negative">
                <AlertTriangle className="mt-0.5 size-3 shrink-0" />
                {previewMutation.error.message}
              </p>
            )}
          </>
        )}

        <div ref={outcome} className="space-y-2.5 empty:hidden">
        {preview && (
          <div className="rounded-lg border bg-card/70 p-2.5">
            <Row label="You pay" value={`${size(preview.pay.amount)} ${preview.pay.symbol}`} />
            <Row label="You receive ≈" value={`${size(preview.receive.amount)} ${preview.receive.symbol}`} strong />
            <Row label="Fee" value={`${size(preview.fee.amount)} ${preview.fee.symbol}`} />
            {Number(preview.receive.amount) > 0 && Number(preview.pay.amount) > 0 && (
              <Row
                label="Price ≈"
                value={`$${price(side === "buy" ? Number(preview.pay.amount) / Number(preview.receive.amount) : Number(preview.receive.amount) / Number(preview.pay.amount))}`}
              />
            )}
            {preview.issues.map((issue) => (
              <p key={issue} className="mt-1 flex items-start gap-1.5 text-[11px] text-mixed">
                <AlertTriangle className="mt-0.5 size-3 shrink-0" /> {issue}
              </p>
            ))}
            <p className={cn("num mt-1.5 text-[10.5px]", remaining < 20 ? "text-negative" : "text-muted-foreground")}>
              {remaining > 0 ? `Quote valid for ${remaining}s` : "Quote expired. Refresh it."}
            </p>
            <button
              onClick={confirm}
              disabled={!s?.enabled || remaining === 0 || executeMutation.isPending}
              className={cn(
                "mt-2 flex w-full items-center justify-center gap-1.5 rounded-md px-3 py-2 text-[12.5px] font-semibold transition-colors disabled:opacity-40",
                armed ? "bg-negative text-white" : side === "buy" ? "bg-primary text-primary-foreground" : "bg-down text-white",
              )}
            >
              {executeMutation.isPending ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" /> Placing order…
                </>
              ) : armed ? (
                "Confirm: real order"
              ) : side === "buy" ? (
                `Buy ${symbol} for $${price(preview.notionalUsd, 2)}`
              ) : (
                `Sell ${size(preview.pay.amount)} ${symbol}`
              )}
            </button>
            {armed && <p className="mt-1 text-center text-[10.5px] text-muted-foreground">Click again within a few seconds to send this order. It moves real funds.</p>}
            {executeMutation.isError && (
              <p className="mt-1.5 flex items-start gap-1.5 text-[11.5px] text-negative">
                <AlertTriangle className="mt-0.5 size-3 shrink-0" />
                {executeMutation.error.message}
              </p>
            )}
          </div>
        )}

        {result && (
          <div className={cn("rounded-lg border p-2.5 text-[12px]", result.status === "complete" ? "border-positive/40 bg-positive/10" : result.status === "failed" ? "border-negative/40 bg-negative/10" : "bg-card/70")}>
            <p className="flex items-center gap-1.5 font-semibold">
              {result.status === "complete" ? <Check className="size-3.5 text-positive" /> : result.status === "failed" ? <AlertTriangle className="size-3.5 text-negative" /> : <Loader2 className="size-3.5 animate-spin" />}
              {result.status === "complete" ? "Order filled" : result.status === "failed" ? "Order failed" : `Order ${result.status}`}
            </p>
            {result.executedQty && <p className="num mt-0.5 text-muted-foreground">Executed {size(result.executedQty)} {symbol}{result.executedVwap ? ` at $${price(result.executedVwap)}` : ""}</p>}
            {result.failureReason && <p className="mt-0.5 text-negative">{result.failureReason}</p>}
            {result.explorerUrl && /^https:\/\//.test(result.explorerUrl) && (
              <a href={result.explorerUrl} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-chart-1 hover:underline">
                View transaction <ExternalLink className="size-3" />
              </a>
            )}
          </div>
        )}

        </div>
        <p className="num text-[10.5px] text-muted-foreground">
          Market orders · max ${s?.maxOrderUsd ?? "—"} each{left !== undefined ? ` · $${price(left, 2)} of $${s?.dailyLimitUsd} left today` : ""}
        </p>
      </div>
    </Panel>
  );
}

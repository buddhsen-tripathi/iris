import { useElapsed, useNow, useTopic } from "@/hooks/useMarket";
import { age, decimalsFor, price } from "@/lib/format";
import { topics, type ReferencePrice } from "@/lib/tm";
import { Empty, Panel } from "./ui";

/** True Markets' weighted reference: per-exchange best bid/offer blended into one quote. */
export function ReferencePanel({ symbol }: { symbol: string }) {
  const { value, rejected } = useTopic<ReferencePrice>(topics.reference(symbol));
  const now = useNow();
  const silent = useElapsed(symbol);
  const ref = value?.data;
  const decimals = decimalsFor(Number(ref?.mid_price ?? 0));

  return (
    <Panel title="Composite reference" meta={ref?.instrument ?? ref?.symbol} delay={220}>
      {rejected || (!ref && silent) ? (
        <Empty>No composite reference for {symbol}.</Empty>
      ) : !ref ? (
        <Empty>Waiting for quotes…</Empty>
      ) : (
        <div className="px-4 py-2">
          <dl className="num grid grid-cols-3 text-[12px]">
            {(
              [
                ["Bid", ref.bid, "text-up"],
                ["Mid", ref.mid_price, "text-foreground font-semibold"],
                ["Ask", ref.ask, "text-down"],
              ] as const
            ).map(([label, value, tone]) => (
              <div key={label} className="flex items-baseline gap-1.5 [&:nth-child(2)]:justify-center [&:nth-child(3)]:justify-end">
                <dt className="kicker">{label}</dt>
                <dd className={tone}>{price(value, decimals)}</dd>
              </div>
            ))}
          </dl>
          <table className="num mt-2 w-full text-[11px]">
            <thead className="kicker text-left">
              <tr>
                <th className="pb-1 font-semibold">Source</th>
                <th className="pb-1 text-right font-semibold">Mid</th>
                <th className="pb-1 text-right font-semibold">Weight</th>
                <th className="pb-1 text-right font-semibold">Age</th>
              </tr>
            </thead>
            <tbody>
              {ref.sources.map((source) => {
                const weight = Number(source.weight_pct);
                // weight_pct is a fraction of one ("0.5" = half).
                const share = weight <= 1 ? weight * 100 : weight;
                return (
                  <tr key={source.source} className="border-t border-border/60">
                    <td className="py-1 font-sans capitalize">{source.source}</td>
                    <td className="py-1 text-right">{price(source.mid_price, decimals)}</td>
                    <td className="py-1 text-right">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-1 w-10 overflow-hidden rounded-full bg-muted">
                          <span className="block h-full bg-chart-1" style={{ width: `${share}%` }} />
                        </span>
                        {share.toFixed(0)}%
                      </span>
                    </td>
                    <td className="py-1 text-right text-muted-foreground">{age(Date.parse(source.timestamp), now)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

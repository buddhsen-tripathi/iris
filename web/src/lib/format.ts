const cache = new Map<string, Intl.NumberFormat>();
const nf = (options: Intl.NumberFormatOptions) => {
  const k = JSON.stringify(options);
  let f = cache.get(k);
  if (!f) cache.set(k, (f = new Intl.NumberFormat("en-US", options)));
  return f;
};

/** Decimal places for a price: 2 above 100, then about four significant figures below that. */
export function decimalsFor(value: number): number {
  const abs = Math.abs(value);
  if (!Number.isFinite(abs) || abs === 0) return 2;
  return Math.min(10, Math.max(2, 3 - Math.floor(Math.log10(abs)) + (abs >= 1 ? 1 : 0)));
}

export function price(value: number | string | undefined, decimals?: number): string {
  const n = Number(value);
  if (value === undefined || !Number.isFinite(n)) return "—";
  const d = decimals ?? decimalsFor(n);
  return nf({ minimumFractionDigits: d, maximumFractionDigits: d }).format(n);
}

export function pct(value: number | string | undefined, digits = 2): string {
  const n = Number(value);
  if (value === undefined || !Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${nf({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Math.abs(n))}%`;
}

export function compact(value: number | string | undefined, prefix = ""): string {
  const n = Number(value);
  if (value === undefined || !Number.isFinite(n)) return "—";
  return prefix + nf({ notation: "compact", maximumFractionDigits: 2 }).format(n);
}

export function size(value: number | string | undefined): string {
  const n = Number(value);
  if (value === undefined || !Number.isFinite(n)) return "—";
  return nf({ maximumFractionDigits: n >= 100 ? 0 : n >= 1 ? 2 : 4 }).format(n);
}

export function age(fromMs: number | undefined, nowMs: number): string {
  if (fromMs === undefined || !Number.isFinite(fromMs)) return "—";
  const s = Math.max(0, Math.round((nowMs - fromMs) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 172800) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export const direction = (value: number | string | undefined) => {
  const n = Number(value);
  return !Number.isFinite(n) || n === 0 ? "flat" : n > 0 ? "up" : "down";
};

import { useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";

// The Iris Owl: Iris's mascot. Ink line art on paper with the vermilion accent, drawn from
// theme tokens so it follows light and dark mode. Motion is CSS-only and honours reduced motion.

export type MascotMood = "idle" | "thinking" | "curious" | "cautious" | "happy" | "sleeping";

// One app-wide switch (footer): every owl hides together, and the choice is remembered.
const STORAGE_KEY = "mascot";
const listeners = new Set<() => void>();
const readOn = () => localStorage.getItem(STORAGE_KEY) !== "off";
export function setMascotOn(on: boolean) {
  localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
  listeners.forEach((listener) => listener());
}
export function useMascotOn() {
  return useSyncExternalStore((notify) => {
    listeners.add(notify);
    return () => listeners.delete(notify);
  }, readOn);
}

const PUPILS: Partial<Record<MascotMood, { dx: number; dy: number; r: number }>> = {
  idle: { dx: 0, dy: 1, r: 6 },
  thinking: { dx: 3.5, dy: -4, r: 5.5 },
  curious: { dx: -1.5, dy: 0.5, r: 7.5 },
  cautious: { dx: 0, dy: 3.5, r: 5 },
};

const INK = "stroke-foreground";
const LINE = { strokeLinecap: "round", strokeLinejoin: "round" } as const;

function Eye({ cx, mood }: { cx: number; mood: MascotMood }) {
  const cy = 44;
  if (mood === "happy") return <path d={`M${cx - 8} ${cy + 3} q8 -10 16 0`} className={cn(INK, "fill-none")} strokeWidth={3.2} {...LINE} />;
  if (mood === "sleeping") return <path d={`M${cx - 8} ${cy} q8 7 16 0`} className={cn(INK, "fill-none")} strokeWidth={3} {...LINE} />;
  const p = PUPILS[mood] ?? PUPILS.idle!;
  return (
    <g>
      <circle cx={cx} cy={cy} r={13} className={cn(INK, "fill-background")} strokeWidth={2.6} />
      <g className="mascot-eye">
        <circle cx={cx + p.dx} cy={cy + p.dy} r={p.r} className="fill-foreground" />
        <circle cx={cx + p.dx - 2.2} cy={cy + p.dy - 2.4} r={1.9} className="fill-background" />
      </g>
    </g>
  );
}

export function Mascot({
  mood = "idle",
  size = 48,
  className,
  title = "Iris Owl",
  animated = true,
}: {
  mood?: MascotMood;
  size?: number;
  className?: string;
  title?: string;
  animated?: boolean;
}) {
  const on = useMascotOn();
  if (!on) return null;
  const tilt = mood === "curious" ? -7 : mood === "thinking" ? 4 : mood === "sleeping" ? 6 : 0;
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      role="img"
      aria-label={`${title} (${mood})`}
      className={cn("mascot shrink-0 overflow-visible", animated && `mascot-animated mascot-${mood}`, className)}
    >
      <title>{title}</title>
      <g className="mascot-body" transform={`rotate(${tilt} 50 60)`}>
        {/* Feet */}
        <path d="M38 89 l-4 6 M38 89 l0 7 M38 89 l4 6 M62 89 l-4 6 M62 89 l0 7 M62 89 l4 6" className="fill-none stroke-chart-1" strokeWidth={2.6} {...LINE} />
        {/* Ear tufts, behind the head */}
        <path d="M24 30 L19 9 L38 21 Z M76 30 L81 9 L62 21 Z" className={cn(INK, "fill-card")} strokeWidth={2.8} {...LINE} />
        {/* Body */}
        <path d="M50 15 C77 15 87 37 87 59 C87 81 71 92 50 92 C29 92 13 81 13 59 C13 37 23 15 50 15 Z" className={cn(INK, "fill-card")} strokeWidth={3} {...LINE} />
        {/* Wings */}
        <path d="M17 50 C8 61 10 77 24 84 C21 72 21 61 17 50 Z M83 50 C92 61 90 77 76 84 C79 72 79 61 83 50 Z" className={cn(INK, "fill-muted")} strokeWidth={2.4} {...LINE} />
        {/* Face disc */}
        <path d="M50 30 C42 24 22 25 21 43 C20 57 35 62 50 58 C65 62 80 57 79 43 C78 25 58 24 50 30 Z" className="fill-muted/70" />
        {/* Belly feathers */}
        <path d="M38 74 l3.5 3 l3.5 -3 M55 74 l3.5 3 l3.5 -3 M46.5 81 l3.5 3 l3.5 -3" className={cn(INK, "fill-none")} strokeWidth={1.7} opacity={0.4} {...LINE} />
        {/* Cheeks */}
        <ellipse cx={25} cy={57} rx={5} ry={2.8} className="fill-chart-1" opacity={mood === "sleeping" ? 0.18 : 0.32} />
        <ellipse cx={75} cy={57} rx={5} ry={2.8} className="fill-chart-1" opacity={mood === "sleeping" ? 0.18 : 0.32} />
        <Eye cx={36} mood={mood} />
        <Eye cx={64} mood={mood} />
        {/* Brows */}
        {mood === "cautious" && <path d="M26 28 L43 32 M74 28 L57 32" className={cn(INK, "fill-none")} strokeWidth={2.6} {...LINE} />}
        {mood === "curious" && <path d="M56 26 q8 -6 17 -2" className={cn(INK, "fill-none")} strokeWidth={2.6} {...LINE} />}
        {/* Beak */}
        <path d="M50 51 L45 56.5 L50 64 L55 56.5 Z" className="fill-chart-1 stroke-foreground" strokeWidth={1.6} {...LINE} />
      </g>
      {mood === "thinking" && (
        <g className="mascot-dots fill-foreground">
          <circle cx={84} cy={20} r={2.2} />
          <circle cx={91} cy={12} r={2.8} />
          <circle cx={99} cy={3} r={3.4} />
        </g>
      )}
      {mood === "sleeping" && (
        <g className="mascot-zzz fill-muted-foreground" fontFamily="var(--font-mono)" fontWeight={700}>
          <text x={80} y={22} fontSize={11}>z</text>
          <text x={89} y={11} fontSize={14}>z</text>
        </g>
      )}
    </svg>
  );
}

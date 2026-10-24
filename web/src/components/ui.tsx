import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { direction, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSection } from "./layout";

/**
 * A titled pane. Inside a layout Section, its header (fixed at the Section's collapsed height) toggles
 * collapse, and the body scrolls when its content outgrows the pane.
 */
export function Panel({
  title,
  meta,
  children,
  className,
  delay = 0,
}: {
  title: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  const section = useSection();
  const collapsed = section?.collapsed ?? false;
  return (
    <section
      className={cn("rise flex min-h-0 flex-1 flex-col", className)}
      style={{ animationDelay: `${delay}ms` }}
      data-ask-panel={typeof title === "string" ? title : undefined}
    >
      <header className="rule-double flex h-9 shrink-0 items-center justify-between gap-2 px-4" onDoubleClick={section?.toggle}>
        {section ? (
          <button
            onClick={section.toggle}
            aria-expanded={!collapsed}
            title={collapsed ? "Expand" : "Collapse"}
            className="-ml-1.5 flex min-w-0 items-center gap-1 rounded-sm px-0.5 text-left hover:text-chart-1"
          >
            <ChevronDown className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", collapsed && "-rotate-90")} />
            <h2 className="truncate text-[13px] leading-none font-semibold">{title}</h2>
          </button>
        ) : (
          <h2 className="text-[13px] leading-none font-semibold">{title}</h2>
        )}
        {meta && <div className="kicker min-w-0 truncate">{meta}</div>}
      </header>
      <div className={cn("scroll-thin flex min-h-0 flex-1 flex-col overflow-auto", collapsed && "hidden")}>{children}</div>
    </section>
  );
}

export function Delta({ value, className, digits }: { value: number | string | undefined; className?: string; digits?: number }) {
  const dir = direction(value);
  return (
    <span
      className={cn(
        "num whitespace-nowrap",
        dir === "up" && "text-up",
        dir === "down" && "text-down",
        dir === "flat" && "text-muted-foreground",
        className,
      )}
    >
      {dir === "up" ? "▲ " : dir === "down" ? "▼ " : ""}
      {pct(value, digits)}
    </span>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly { id: T; label: ReactNode; title?: string }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex items-center rounded-md border bg-card/60 p-0.5">
      {options.map((option) => (
        <button
          key={option.id}
          role="radio"
          aria-checked={option.id === value}
          title={option.title}
          onClick={() => onChange(option.id)}
          className={cn(
            "num rounded-[5px] px-2 py-1 text-[11px] font-medium transition-colors",
            option.id === value ? "bg-primary text-primary-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ pressed, onClick, children, title }: { pressed: boolean; onClick: () => void; children: ReactNode; title?: string }) {
  return (
    <button
      aria-pressed={pressed}
      title={title}
      onClick={onClick}
      className={cn(
        "num rounded-md border px-2 py-1 text-[11px] font-medium transition-colors",
        pressed ? "border-foreground/70 bg-accent text-foreground" : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function AssetIcon({ src, symbol, className }: { src?: string; symbol: string; className?: string }) {
  return src ? (
    <img src={src} alt="" loading="lazy" className={cn("size-5 shrink-0 rounded-full bg-muted object-cover", className)} />
  ) : (
    <span
      aria-hidden
      className={cn("grid size-5 shrink-0 place-items-center rounded-full bg-muted text-[10px] font-medium text-muted-foreground", className)}
    >
      {symbol.slice(0, 1)}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-4 py-6 text-center text-xs text-muted-foreground">{children}</p>;
}

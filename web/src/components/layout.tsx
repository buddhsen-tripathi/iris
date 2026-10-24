import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Group, Panel as ResizablePanel, Separator, useDefaultLayout, usePanelRef, type Orientation } from "react-resizable-panels";
import { cn } from "@/lib/utils";

// Resizable, collapsible desk layout. Each Section is a resizable pane; the Panel header inside it
// (components/ui.tsx) becomes the collapse toggle. Sizes and collapsed state persist per group.

/** Height of a Panel header; a collapsed section shrinks to exactly this. */
const HEADER_PX = 36;

type SectionState = { collapsed: boolean; toggle: () => void };
const SectionContext = createContext<SectionState | null>(null);

/** Collapse state of the enclosing Section, if any. */
export const useSection = () => useContext(SectionContext);

export function DeskGroup({ id, orientation, children, className }: { id: string; orientation: Orientation; children: ReactNode; className?: string }) {
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({ id: `desk:${id}`, storage: localStorage });
  return (
    <Group id={id} orientation={orientation} defaultLayout={defaultLayout} onLayoutChanged={onLayoutChanged} className={cn("min-h-0 min-w-0", className)}>
      {children}
    </Group>
  );
}

/** A collapsible pane in a vertical group. Sizes accept the library's units: numbers are pixels, strings like "40%" are percentages. */
export function Section({
  id,
  defaultSize,
  minSize = 90,
  children,
  className,
}: {
  id: string;
  defaultSize?: number | string;
  minSize?: number | string;
  children: ReactNode;
  className?: string;
}) {
  const ref = usePanelRef();
  const [collapsed, setCollapsed] = useState(false);
  const toggle = useCallback(() => {
    const panel = ref.current;
    if (!panel) return;
    if (panel.isCollapsed()) panel.expand();
    else panel.collapse();
  }, [ref]);
  return (
    <ResizablePanel
      id={id}
      panelRef={ref}
      collapsible
      collapsedSize={HEADER_PX}
      minSize={minSize}
      defaultSize={defaultSize}
      onResize={(size) => setCollapsed(size.inPixels <= HEADER_PX + 1)}
      className={cn("flex h-full min-h-0 flex-col overflow-hidden", className)}
      data-collapsed={collapsed || undefined}
    >
      <SectionContext.Provider value={{ collapsed, toggle }}>{children}</SectionContext.Provider>
    </ResizablePanel>
  );
}

/** A resizable column of the desk (not collapsible itself; its sections are). */
export function Column({
  id,
  defaultSize,
  minSize,
  maxSize,
  children,
  className,
  fixed,
}: {
  id: string;
  defaultSize?: number | string;
  minSize?: number | string;
  maxSize?: number | string;
  children: ReactNode;
  className?: string;
  /** Keep this column's pixel width when the window resizes (side rails); the main column absorbs the change. */
  fixed?: boolean;
}) {
  return (
    <ResizablePanel
      id={id}
      defaultSize={defaultSize}
      minSize={minSize}
      maxSize={maxSize}
      groupResizeBehavior={fixed ? "preserve-pixel-size" : "preserve-relative-size"}
      className={cn("flex h-full min-h-0 min-w-0 flex-col", className)}
    >
      {children}
    </ResizablePanel>
  );
}

/** Drag handle between panes; double-click resets the neighbouring pane to its default size. */
export function ResizeHandle({ orientation }: { orientation: Orientation }) {
  return (
    <Separator
      className={cn(
        "relative shrink-0 bg-border transition-colors outline-none",
        "data-[separator=hover]:bg-chart-1/60 data-[separator=active]:bg-chart-1 focus-visible:bg-chart-1",
        orientation === "horizontal" ? "w-px" : "h-px",
      )}
    />
  );
}

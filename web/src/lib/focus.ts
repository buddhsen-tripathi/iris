import type { Focus } from "./ai";

// Point & ask: turn whatever the user pointed at into a compact, text-only description for the model.

const MIN_TEXT = 8;
const WIDEN_TO = 80;
const clean = (text: string | null | undefined, max: number) => (text ?? "").replace(/\s+/g, " ").trim().slice(0, max);
const textOf = (el: Element) => clean((el as HTMLElement).innerText ?? el.textContent, 4000);

/** Elements that belong to the point & ask UI itself (or must stay clickable) are skipped. */
const IGNORE = "[data-ask-ignore]";

/** Rows and controls are picked whole, so a click on one number brings its row. */
const UNIT = "li, tr, button, a, [role=radio], [role=option]";

/**
 * Picks the meaningful element around a pointer target, never beyond its panel: the enclosing row or
 * control if there is one, otherwise the nearest ancestor with a few characters including a letter
 * (so a bare number brings its label). Chart canvases resolve to the panel, whose legend has the numbers.
 */
export function pickElement(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element) || target.closest(IGNORE)) return null;
  const panel = target.closest<HTMLElement>("[data-ask-panel]");
  if (target.closest("canvas, .tv-lightweight-charts")) return target.closest<HTMLElement>("[data-ask-scope]") ?? panel ?? (target.parentElement as HTMLElement | null);
  const unit = target.closest<HTMLElement>(UNIT);
  if (unit && (!panel || panel.contains(unit))) return unit;
  let el = target as HTMLElement;
  const meaningful = (node: HTMLElement) => {
    const text = textOf(node);
    return text.length >= MIN_TEXT && /[A-Za-z]/.test(text);
  };
  while (el.parentElement && el !== panel && !meaningful(el)) el = el.parentElement;
  // A label alone ("Funding 1h") is less useful than label + value: widen while the block stays small.
  while (el.parentElement && el !== panel && el.parentElement !== panel && textOf(el.parentElement).length <= WIDEN_TO) el = el.parentElement;
  return el;
}

/** Text-only description of a picked element and its panel. */
export function describe(el: HTMLElement): Focus {
  const panelEl = el.closest<HTMLElement>("[data-ask-panel]");
  const panelName = panelEl?.dataset.askPanel ?? clean(panelEl?.querySelector("h2")?.textContent, 80);
  const labelled = el.closest<HTMLElement>("[aria-label], [title]");
  const label = clean(el.getAttribute("aria-label") ?? el.getAttribute("title") ?? labelled?.getAttribute("aria-label") ?? labelled?.getAttribute("title"), 200);
  const text = clean(el.innerText, 2000) || label || "(no visible text)";
  const surroundings = panelEl && panelEl !== el ? clean(panelEl.innerText, 4000) : undefined;
  return { panel: panelName || "Desk", ...(label && { label }), text, ...(surroundings && { surroundings }) };
}

import { useCallback, useSyncExternalStore } from "react";

type Theme = "light" | "dark";

const read = (): Theme => (document.documentElement.classList.contains("dark") ? "dark" : "light");

function subscribe(notify: () => void) {
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, read);
  const toggle = useCallback(() => {
    const next = read() === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    localStorage.setItem("theme", next);
  }, []);
  return { theme, toggle };
}

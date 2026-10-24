import { useCallback, useState } from "react";

/** useState persisted to localStorage as JSON. */
export function useStored<T>(name: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(name);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (next: T | ((previous: T) => T)) =>
      setValue((previous) => {
        const resolved = typeof next === "function" ? (next as (previous: T) => T)(previous) : next;
        localStorage.setItem(name, JSON.stringify(resolved));
        return resolved;
      }),
    [name],
  );
  return [value, set] as const;
}

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { marketSocket } from "@/lib/socket";

type Snapshot<T> = { data: T; receivedAt: number } | undefined;

/** Latest payload for a WebSocket topic, or undefined until the first message. `null` subscribes to nothing. */
export function useTopic<T>(topic: string | null): { value: Snapshot<T>; rejected?: string } {
  const subscribe = useCallback((notify: () => void) => (topic ? marketSocket.subscribe(topic, notify) : () => {}), [topic]);
  const value = useSyncExternalStore(subscribe, () => (topic ? marketSocket.snapshot<T>(topic) : undefined));
  const rejected = useSyncExternalStore(subscribe, () => (topic ? marketSocket.rejection(topic) : undefined));
  return { value, rejected };
}

export function useSocketStatus() {
  return useSyncExternalStore(
    (notify) => marketSocket.onStatus(notify),
    () => marketSocket.status,
  );
}

/** True once `ms` has passed since `key` last changed; for "this stream never published" states. */
export function useElapsed(key: string, ms = 8000) {
  const [elapsed, setElapsed] = useState<string | null>(null);
  useEffect(() => {
    const id = setTimeout(() => setElapsed(key), ms);
    return () => clearTimeout(id);
  }, [key, ms]);
  return elapsed === key;
}

/** Re-renders every `ms` so relative ages ("3s ago") stay current. */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

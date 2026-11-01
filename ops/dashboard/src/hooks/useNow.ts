import { useMemo, useSyncExternalStore } from "react";

interface Ticker {
  now: number;
  listeners: Set<() => void>;
  timer: ReturnType<typeof setInterval> | null;
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => number;
}

const tickers = new Map<number, Ticker>();

function tickerFor(intervalMs: number): Ticker {
  let ticker = tickers.get(intervalMs);
  if (!ticker) {
    const created: Ticker = {
      now: Date.now(),
      listeners: new Set(),
      timer: null,
      // subscribe/getSnapshot must keep the same identity for the life of the ticker: a new function on every render
      // makes useSyncExternalStore resubscribe and re-render forever.
      subscribe: (listener) => {
        if (created.listeners.size === 0) created.now = Date.now(); // idle ticker: refresh before first use
        created.listeners.add(listener);
        if (!created.timer) {
          created.timer = setInterval(() => {
            created.now = Date.now();
            created.listeners.forEach((fn) => fn());
          }, intervalMs);
        }
        return () => {
          created.listeners.delete(listener);
          if (created.listeners.size === 0 && created.timer) {
            clearInterval(created.timer);
            created.timer = null;
          }
        };
      },
      getSnapshot: () => created.now,
    };
    ticker = created;
    tickers.set(intervalMs, ticker);
  }
  return ticker;
}

/**
 * Current time in epoch ms, re-rendering the component every `intervalMs`. All components that use the same interval
 * share ONE setInterval, so 100 ticking cards cost one timer.
 */
export function useNow(intervalMs = 1000): number {
  const ticker = useMemo(() => tickerFor(intervalMs), [intervalMs]);
  return useSyncExternalStore(ticker.subscribe, ticker.getSnapshot, () => Date.now());
}

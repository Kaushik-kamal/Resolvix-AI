/**
 * Reconnecting Server-Sent Events client (framework-free, so it is unit-testable with a fake EventSource).
 *
 * Why not rely on the browser's own retry: when the server answers 401 or goes down, EventSource moves to CLOSED and
 * never retries by itself. This client closes the source on every error and opens a fresh one after an exponential
 * backoff (1 s, 2 s, 4 s ... capped at 30 s). The delay resets once a connection opens.
 *
 * After a RE-connect (not the first connect) `onOpen(true)` fires so the caller can refetch state: events missed
 * while disconnected are not replayed by the API (see ops/docs/SSE_EVENTS.md).
 */
import { STREAM_EVENT_NAMES } from "../api/extra";
import type { StreamEventMap, StreamEventName } from "../api/extra";

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";

/** The subset of the EventSource API this client needs (a fake in tests implements the same shape). */
export interface EventSourceLike {
  readonly readyState: number;
  onopen: ((ev: Event) => unknown) | null;
  onerror: ((ev: Event) => unknown) | null;
  addEventListener(type: string, listener: (ev: MessageEvent) => unknown): void;
  removeEventListener?(type: string, listener: (ev: MessageEvent) => unknown): void;
  close(): void;
}
export type EventSourceCtor = new (url: string, init?: { withCredentials?: boolean }) => EventSourceLike;

export interface BackoffOptions {
  /** first retry delay in ms (default 1000) */
  baseMs?: number;
  /** upper bound in ms (default 30000) */
  maxMs?: number;
  /** growth factor (default 2) */
  factor?: number;
}

/** Delay before reconnect attempt number `attempt` (1-based): base * factor^(attempt-1), capped at max. */
export function backoffDelay(attempt: number, { baseMs = 1000, maxMs = 30_000, factor = 2 }: BackoffOptions = {}): number {
  const n = Math.max(1, Math.floor(attempt));
  return Math.min(maxMs, Math.round(baseMs * Math.pow(factor, n - 1)));
}

export interface StreamState {
  status: ConnectionStatus;
  /** reconnect attempts since the last successful open (0 while open) */
  attempt: number;
  /** ms until the next attempt while status is "reconnecting", else null */
  retryInMs: number | null;
  /** epoch ms of the last received event or open, null before the first */
  lastActivityAt: number | null;
}

export type StreamListener = <N extends StreamEventName>(name: N, data: StreamEventMap[N]) => void;

export interface EventStreamClientOptions {
  url: string;
  /** Constructor to use; defaults to the global EventSource. Tests inject a fake. */
  EventSourceImpl?: EventSourceCtor;
  withCredentials?: boolean;
  backoff?: BackoffOptions;
  /** Called for every named event with its parsed JSON payload. */
  onEvent?: StreamListener;
  /** Called whenever status/attempt changes. */
  onState?: (state: StreamState) => void;
  /** Called when a connection opens; `reconnected` is true unless it is the first open of this client. */
  onOpen?: (reconnected: boolean) => void;
  /**
   * Called on every connection error with the number of consecutive failed attempts so far (1 = first failure).
   * The caller can probe the session here: a 401 is invisible to EventSource, which only reports "error".
   */
  onError?: (attempt: number) => void;
  /** Called for a data line that is not valid JSON (the event is dropped). */
  onParseError?: (name: string, raw: string) => void;
  /** Event names to listen for (default: every name in SSE_EVENTS.md). */
  eventNames?: readonly StreamEventName[];
  now?: () => number;
}

export interface EventStreamClient {
  start(): void;
  /** Stop for good: closes the source and cancels any pending reconnect. */
  close(): void;
  getState(): StreamState;
}

export function createEventStreamClient(options: EventStreamClientOptions): EventStreamClient {
  const Impl = options.EventSourceImpl ?? (globalThis as unknown as { EventSource?: EventSourceCtor }).EventSource;
  const names = options.eventNames ?? STREAM_EVENT_NAMES;
  const now = options.now ?? Date.now;

  let source: EventSourceLike | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  let everOpened = false;
  let state: StreamState = { status: "connecting", attempt: 0, retryInMs: null, lastActivityAt: null };

  function setState(patch: Partial<StreamState>): void {
    state = { ...state, ...patch };
    options.onState?.(state);
  }

  function detach(): void {
    if (!source) return;
    source.onopen = null;
    source.onerror = null;
    try {
      source.close();
    } catch {
      /* already closed */
    }
    source = null;
  }

  function connect(): void {
    if (stopped) return;
    if (!Impl) {
      setState({ status: "closed", retryInMs: null });
      return;
    }
    timer = null;
    detach();
    const es = new Impl(options.url, { withCredentials: options.withCredentials ?? true });
    source = es;

    es.onopen = () => {
      if (stopped || source !== es) return;
      const reconnected = everOpened;
      everOpened = true;
      setState({ status: "open", attempt: 0, retryInMs: null, lastActivityAt: now() });
      options.onOpen?.(reconnected);
    };

    for (const name of names) {
      es.addEventListener(name, (ev: MessageEvent) => {
        if (stopped || source !== es) return;
        const raw = typeof ev.data === "string" ? ev.data : String(ev.data);
        let parsed: unknown;
        try {
          parsed = JSON.parse(raw);
        } catch {
          options.onParseError?.(name, raw);
          return;
        }
        state = { ...state, lastActivityAt: now() };
        options.onEvent?.(name, parsed as never);
      });
    }

    es.onerror = () => {
      if (stopped || source !== es) return;
      // Take over from the browser: whether it is CONNECTING or CLOSED, drop it and retry on our own schedule.
      detach();
      const attempt = state.attempt + 1;
      const delay = backoffDelay(attempt, options.backoff);
      setState({ status: "reconnecting", attempt, retryInMs: delay });
      timer = setTimeout(connect, delay);
      try {
        options.onError?.(attempt);
      } catch {
        /* a failing probe must never break the reconnect loop */
      }
    };
  }

  return {
    start() {
      if (stopped || source || timer) return;
      connect();
    },
    close() {
      stopped = true;
      if (timer) clearTimeout(timer);
      timer = null;
      detach();
      setState({ status: "closed", retryInMs: null });
    },
    getState: () => state,
  };
}

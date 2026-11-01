import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { handleUnauthorized, isApiError, me as probeSession, streamUrl } from "../api/client";
import type { CallTurnEvent, StreamEventMap, StreamEventName } from "../api/extra";
import {
  createEventStreamClient,
  type BackoffOptions,
  type EventSourceCtor,
  type StreamState,
} from "../lib/sse";
import { invalidationsFor, invalidationsOnReconnect } from "./invalidation";

export type StreamHandler = (name: StreamEventName, data: StreamEventMap[StreamEventName]) => void;

export interface EventStreamValue {
  /** connection status, attempt counter, next retry delay */
  state: StreamState;
  /** Subscribe to every stream event. Returns an unsubscribe function. */
  subscribe: (handler: StreamHandler) => () => void;
  /** Latest call.turn event per call_id since this page loaded (the REST list has no last-turn field). */
  lastTurns: Record<string, CallTurnEvent>;
}

/** Consecutive stream errors before the session is probed with GET /v1/auth/me (a 401 is invisible to EventSource). */
export const SESSION_PROBE_AFTER_ATTEMPTS = 2;

const INITIAL: StreamState = { status: "connecting", attempt: 0, retryInMs: null, lastActivityAt: null };

const noop = () => () => undefined;
const EventStreamContext = createContext<EventStreamValue>({ state: INITIAL, subscribe: noop, lastTurns: {} });

export interface UseEventStreamConnectionOptions {
  /** Defaults to GET /v1/stream of the configured API base. */
  url?: string;
  /** Inject a fake in tests. */
  EventSourceImpl?: EventSourceCtor;
  backoff?: BackoffOptions;
  /** false = do not connect (e.g. before login). Default true. */
  enabled?: boolean;
}

/**
 * Opens the EventSource on /v1/stream (withCredentials) and keeps it alive with exponential backoff. For every event
 * it invalidates the matching TanStack queries (see stream/invalidation.ts) and then calls the subscribers.
 * Mount it ONCE: EventStreamProvider does. Components read it through useEventStream().
 */
export function useEventStreamConnection(options: UseEventStreamConnectionOptions = {}): EventStreamValue {
  const { url, EventSourceImpl, backoff, enabled = true } = options;
  const queryClient = useQueryClient();
  const handlers = useRef(new Set<StreamHandler>());
  const [state, setState] = useState<StreamState>(INITIAL);
  const [lastTurns, setLastTurns] = useState<Record<string, CallTurnEvent>>({});

  useEffect(() => {
    if (!enabled) return;
    let probing = false;
    // eslint-disable-next-line prefer-const -- referenced by onError before the assignment completes
    let client: ReturnType<typeof createEventStreamClient>;
    client = createEventStreamClient({
      url: url ?? streamUrl(),
      EventSourceImpl,
      backoff,
      withCredentials: true,
      onState: setState,
      // L11: after repeated errors ask the API whether the session is still valid. 401 = expired: stop reconnecting
      // (it would loop forever) and go to /login?expired=1. Anything else (network down, 5xx, 200) keeps retrying.
      onError: (attempt) => {
        if (attempt < SESSION_PROBE_AFTER_ATTEMPTS || probing) return;
        probing = true;
        probeSession()
          .catch((err: unknown) => {
            if (isApiError(err) && err.status === 401) {
              client.close();
              handleUnauthorized();
            }
          })
          .finally(() => {
            probing = false;
          });
      },
      onOpen: (reconnected) => {
        if (!reconnected) return;
        for (const queryKey of invalidationsOnReconnect()) void queryClient.invalidateQueries({ queryKey });
      },
      onEvent: (name, data) => {
        if (name === "call.turn") {
          const turn = data as CallTurnEvent;
          setLastTurns((prev) => ({ ...prev, [turn.call_id]: turn }));
        }
        for (const queryKey of invalidationsFor(name, data)) void queryClient.invalidateQueries({ queryKey });
        handlers.current.forEach((handler) => {
          try {
            handler(name, data);
          } catch (err) {
            console.error("stream handler failed", err);
          }
        });
      },
    });
    client.start();
    return () => client.close();
  }, [url, EventSourceImpl, backoff, enabled, queryClient]);

  const subscribe = useCallback((handler: StreamHandler) => {
    handlers.current.add(handler);
    return () => {
      handlers.current.delete(handler);
    };
  }, []);

  return useMemo(() => ({ state, subscribe, lastTurns }), [state, subscribe, lastTurns]);
}

export interface EventStreamProviderProps extends UseEventStreamConnectionOptions {
  children: ReactNode;
}

export function EventStreamProvider({ children, ...options }: EventStreamProviderProps) {
  const value = useEventStreamConnection(options);
  return <EventStreamContext.Provider value={value}>{children}</EventStreamContext.Provider>;
}

/** Connection state, subscribe() and lastTurns from the nearest EventStreamProvider. */
export function useEventStream(): EventStreamValue {
  return useContext(EventStreamContext);
}

/**
 * Run `handler` for one event name (or all events when `name` is null). The latest handler is always used, so it can
 * close over component state without re-subscribing.
 */
export function useStreamEvent<N extends StreamEventName>(
  name: N | null,
  handler: (data: StreamEventMap[N], name: N) => void,
): void {
  const { subscribe } = useEventStream();
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  useEffect(
    () =>
      subscribe((eventName, data) => {
        if (name === null || eventName === name) latest.current(data as StreamEventMap[N], eventName as N);
      }),
    [subscribe, name],
  );
}

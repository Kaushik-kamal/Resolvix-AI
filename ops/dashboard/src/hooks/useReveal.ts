/**
 * "Reveal numbers" for a detail view (ticket drawer, call detail), L12.
 *
 * Every `?reveal=true` request writes an audit row (`number_revealed`), so:
 *  - the revealed copy is fetched ONCE per explicit click (queryClient.fetchQuery), never by an SSE invalidation, a
 *    window focus or a reconnect: the query below is `enabled: false`, so "active" invalidation skips it, and its
 *    queryFn refuses to run if something refetches it anyway;
 *  - Hide and unmount (drawer closed, call view left) remove the revealed query from the React Query cache
 *    (removeQueries), so the full numbers cannot linger for the 5 minute gc window.
 * The masked detail query stays a normal query and keeps refreshing from the stream.
 */
import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

export interface RevealState<T> {
  /** the user pressed Reveal and the revealed copy has arrived */
  revealed: boolean;
  /** the revealed response while `revealed`, else undefined */
  data: T | undefined;
  /** the one reveal request is in flight */
  pending: boolean;
  /** last reveal failure (cleared by the next click or by Hide) */
  error: unknown;
  /** Reveal when hidden, Hide when revealed */
  toggle: () => void;
  hide: () => void;
}

export function useReveal<T>(queryKey: QueryKey, fetcher: (signal?: AbortSignal) => Promise<T>): RevealState<T> {
  const queryClient = useQueryClient();
  const [revealed, setRevealed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const mounted = useRef(true);
  const keyRef = useRef(queryKey);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    keyRef.current = queryKey;
    fetcherRef.current = fetcher;
  });

  // Subscribes to the cached revealed copy. Never fetches by itself.
  const cached = useQuery<T>({
    queryKey,
    queryFn: () => Promise.reject(new Error("The revealed copy is fetched only by an explicit Reveal click")),
    enabled: false,
    staleTime: Infinity,
    retry: false,
  });

  const drop = useCallback(() => {
    queryClient.removeQueries({ queryKey: keyRef.current, exact: true });
  }, [queryClient]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      drop(); // drawer closed / view left: the full numbers leave the cache with it
    };
  }, [drop]);

  const hide = useCallback(() => {
    setRevealed(false);
    setError(null);
    drop();
  }, [drop]);

  const reveal = useCallback(async () => {
    setPending(true);
    setError(null);
    try {
      await queryClient.fetchQuery({
        queryKey: keyRef.current,
        queryFn: ({ signal }) => fetcherRef.current(signal),
        staleTime: 0,
      });
      if (!mounted.current) {
        drop(); // closed while the request was in flight
        return;
      }
      setRevealed(true);
    } catch (err) {
      drop();
      if (mounted.current) setError(err);
    } finally {
      if (mounted.current) setPending(false);
    }
  }, [queryClient, drop]);

  const toggle = useCallback(() => {
    if (revealed) hide();
    else if (!pending) void reveal();
  }, [revealed, pending, hide, reveal]);

  return { revealed, data: revealed ? cached.data : undefined, pending, error, toggle, hide };
}

/**
 * Which TanStack Query keys each SSE event invalidates. Pure so it can be tested and documented (COMPONENTS.md).
 *
 *  call.started    calls lists
 *  call.turn       calls lists (NOT call detail: every detail GET writes a transcript_viewed audit row)
 *  call.ended      calls lists + that call's detail
 *  ticket.created  tickets lists
 *  alert.p1        tickets lists (same ticket as ticket.created, harmless duplicate)
 *  ticket.updated  tickets lists + that ticket's detail + its events (status SMS lands in the events)
 *  gap.created     gaps
 *  (re)connect     calls, tickets, gaps: events missed while offline are not replayed
 */
import type { QueryKey } from "@tanstack/react-query";
import { qk } from "../api/queryKeys";
import type { StreamEventMap, StreamEventName } from "../api/extra";

export function invalidationsFor<N extends StreamEventName>(name: N, data: StreamEventMap[N]): QueryKey[] {
  switch (name) {
    case "call.started":
    case "call.turn":
      return [qk.calls.lists()];
    case "call.ended":
      return [qk.calls.lists(), qk.calls.detailAny((data as StreamEventMap["call.ended"]).call_id)];
    case "ticket.created":
    case "alert.p1":
      return [qk.tickets.lists()];
    case "ticket.updated": {
      const id = (data as StreamEventMap["ticket.updated"]).ticket_id;
      return [qk.tickets.lists(), qk.tickets.detailAny(id), qk.tickets.events(id)];
    }
    case "gap.created":
      return [qk.gaps.all];
    default:
      return [];
  }
}

/** Keys refetched after the stream reconnects. */
export function invalidationsOnReconnect(): QueryKey[] {
  return [qk.calls.all, qk.tickets.all, qk.gaps.all];
}

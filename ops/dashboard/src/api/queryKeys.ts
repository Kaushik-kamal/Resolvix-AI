/**
 * TanStack Query keys. Keys are hierarchical so that invalidating a prefix refreshes everything below it:
 *   invalidateQueries({ queryKey: qk.calls.all })  -> every call list and detail
 *   invalidateQueries({ queryKey: qk.tickets.lists() }) -> every ticket list regardless of filters
 * Always build keys through this object so the SSE invalidation (useEventStream) keeps matching.
 */
import type { ListCallsParams, ListTicketsParams, ListKbEntriesParams } from "./client";

export const qk = {
  me: ["auth", "me"] as const,
  health: ["health"] as const,

  calls: {
    all: ["calls"] as const,
    lists: () => ["calls", "list"] as const,
    list: (params: ListCallsParams = {}) => ["calls", "list", params] as const,
    detail: (callId: string, reveal = false) => ["calls", "detail", callId, { reveal }] as const,
    /** prefix for every variant (masked/revealed) of one call detail */
    detailAny: (callId: string) => ["calls", "detail", callId] as const,
  },

  tickets: {
    all: ["tickets"] as const,
    lists: () => ["tickets", "list"] as const,
    list: (params: ListTicketsParams = {}) => ["tickets", "list", params] as const,
    detail: (ticketId: string, reveal = false) => ["tickets", "detail", ticketId, { reveal }] as const,
    detailAny: (ticketId: string) => ["tickets", "detail", ticketId] as const,
    events: (ticketId: string) => ["tickets", "events", ticketId] as const,
  },

  gaps: {
    all: ["gaps"] as const,
    clusters: ["gaps", "clusters"] as const,
  },

  kb: {
    all: ["kb"] as const,
    entries: (params: ListKbEntriesParams = {}) => ["kb", "entries", params] as const,
    entriesAny: ["kb", "entries"] as const,
    publishes: ["kb", "publishes"] as const,
  },

  config: {
    departments: ["config", "departments"] as const,
    urgencyRules: ["config", "urgency-rules"] as const,
  },
};

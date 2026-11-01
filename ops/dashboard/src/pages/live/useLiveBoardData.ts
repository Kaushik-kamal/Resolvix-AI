import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../../api/client";
import type { CallSummary, TicketRow } from "../../api/extra";
import { qk } from "../../api/queryKeys";
import { useSessionUser } from "../../auth/AuthContext";
import { useNow } from "../../hooks/useNow";
import { istDateKey, startOfTodayIST } from "../../lib/format";
import { groupByPriority, prioritySort } from "../../lib/prioritySort";

/** Call outcomes counted as "escalated" on the counts row (a human took over, or it was an emergency). */
export const ESCALATED_OUTCOMES: ReadonlySet<string> = new Set(["escalated", "transferred", "emergency"]);
/** Ticket statuses that still need work: shown on the board and counted as "open". */
export const ACTIVE_TICKET_STATUSES = ["open", "in_progress"] as const;
const TICKET_LIMIT = 200;
const SAFETY_REFETCH_MS = 60_000;

export interface BoardCounts {
  callsToday: number;
  answeredByAi: number;
  escalated: number;
  p1Open: number;
}

/** Pure: the four numbers of the counts row. */
export function computeCounts(todayCalls: readonly CallSummary[], activeTickets: readonly TicketRow[]): BoardCounts {
  return {
    callsToday: todayCalls.length,
    answeredByAi: todayCalls.filter((c) => c.ai_resolved === true).length,
    escalated: todayCalls.filter((c) => c.outcome != null && ESCALATED_OUTCOMES.has(c.outcome)).length,
    p1Open: activeTickets.filter(
      (t) => t.priority === "P1" && (ACTIVE_TICKET_STATUSES as readonly string[]).includes(t.status),
    ).length,
  };
}

/**
 * Data for the live board. SSE events invalidate these queries (stream/invalidation.ts); a 60 s refetch is only a
 * safety net. Query keys: calls list {active}, calls list {from: start of today IST}, tickets list {status}.
 *
 * Staff sessions (M4): the API scopes calls to those linked to a ticket of the staff member's department and sends no
 * call.* events, so "calls today / answered by AI / escalated" would be misleading. The "today" query is not even
 * issued for staff (isStaff = true); the page replaces those stats with an explanatory note.
 */
export function useLiveBoardData() {
  const isStaff = useSessionUser()?.role === "staff";
  const now = useNow(60_000);
  const dayKey = istDateKey(new Date(now));
  // eslint-disable-next-line react-hooks/exhaustive-deps -- recomputed only when the IST calendar day changes
  const todayFrom = useMemo(() => startOfTodayIST(new Date(now)), [dayKey]);

  const active = useQuery({
    queryKey: qk.calls.list({ active: true, limit: 100 }),
    queryFn: ({ signal }) => api.listCalls({ active: true, limit: 100 }, signal),
    refetchInterval: SAFETY_REFETCH_MS,
  });
  const today = useQuery({
    queryKey: qk.calls.list({ from: todayFrom, limit: 1000 }),
    queryFn: ({ signal }) => api.listCalls({ from: todayFrom, limit: 1000 }, signal),
    refetchInterval: SAFETY_REFETCH_MS,
    enabled: !isStaff,
  });
  const open = useQuery({
    queryKey: qk.tickets.list({ status: "open", limit: TICKET_LIMIT }),
    queryFn: ({ signal }) => api.listTickets({ status: "open", limit: TICKET_LIMIT }, signal),
    refetchInterval: SAFETY_REFETCH_MS,
  });
  const inProgress = useQuery({
    queryKey: qk.tickets.list({ status: "in_progress", limit: TICKET_LIMIT }),
    queryFn: ({ signal }) => api.listTickets({ status: "in_progress", limit: TICKET_LIMIT }, signal),
    refetchInterval: SAFETY_REFETCH_MS,
  });

  const activeCalls = useMemo(
    () => [...(active.data?.items ?? [])].sort((a, b) => b.started_at.localeCompare(a.started_at)),
    [active.data],
  );
  const tickets = useMemo(
    () => prioritySort([...(open.data?.items ?? []), ...(inProgress.data?.items ?? [])]),
    [open.data, inProgress.data],
  );
  const columns = useMemo(() => groupByPriority(tickets), [tickets]);
  const counts = useMemo(() => computeCounts(today.data?.items ?? [], tickets), [today.data, tickets]);

  const ticketsError = open.error ?? inProgress.error;
  return {
    isStaff,
    activeCalls,
    callsLoading: active.isPending,
    callsError: active.error,
    refetchCalls: () => void active.refetch(),
    tickets,
    columns,
    ticketsLoading: open.isPending || inProgress.isPending,
    ticketsError,
    refetchTickets: () => {
      void open.refetch();
      void inProgress.refetch();
    },
    counts,
    countsLoading: (!isStaff && today.isPending) || open.isPending || inProgress.isPending,
    countsError: isStaff ? null : today.error,
    refetchCounts: () => void today.refetch(),
  };
}

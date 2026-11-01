import { useQuery } from "@tanstack/react-query";
import { RefreshCw, X } from "lucide-react";
import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { api, qk, type CallSummary } from "../../api";
import {
  Button,
  DataTable,
  PageHeader,
  Panel,
  StatusChip,
  type Column,
} from "../../components";
import { formatDateTime, formatDuration, humanize, secondsBetween } from "../../lib/format";
import { CallDetailView } from "./CallDetailView";
import { buildCallListParams, CALL_OUTCOMES, isActiveCall, lastTurnText, yesNo } from "./callLogic";

const columns: Column<CallSummary>[] = [
  {
    key: "time",
    header: "Started",
    cell: (c) => (
      <span className="whitespace-nowrap text-xs" title={c.call_id}>
        {formatDateTime(c.started_at)}
      </span>
    ),
  },
  { key: "number", header: "Number", cell: (c) => <span className="font-mono text-xs">{c.caller_number ?? "—"}</span> },
  { key: "channel", header: "Channel", cell: (c) => <span className="text-xs">{c.channel}</span> },
  { key: "lang", header: "Lang", cell: (c) => <span className="text-xs">{c.lang}</span> },
  {
    key: "outcome",
    header: "Outcome",
    cell: (c) =>
      c.outcome ? <StatusChip status={c.outcome} /> : isActiveCall(c) ? <StatusChip status="in_progress" label="In progress" /> : <span className="text-ink-faint">—</span>,
  },
  { key: "ai", header: "AI resolved", cell: (c) => <span className="text-xs">{yesNo(c.ai_resolved)}</span> },
  { key: "turns", header: "Turns", align: "right", cell: (c) => <span className="tabular-nums">{c.turns_count}</span> },
  {
    key: "duration",
    header: "Duration",
    align: "right",
    cell: (c) => <span className="tabular-nums text-xs">{c.ended_at ? formatDuration(secondsBetween(c.started_at, c.ended_at)) : "—"}</span>,
  },
  { key: "last", header: "Last turn (path / tier)", cell: (c) => <span className="text-xs">{lastTurnText(c.last_turn)}</span> },
];

/** Calls: list (`/calls`) and detail (`/calls?call=<id>`). */
export default function CallsPage() {
  const [params, setParams] = useSearchParams();
  const callId = params.get("call");
  const setParam = useCallback(
    (key: string, value: string) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) next.set(key, value);
          else next.delete(key);
          return next;
        },
        { replace: key !== "call" || value === "" },
      );
    },
    [setParams],
  );

  const clearFilters = useCallback(() => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("outcome");
        next.delete("active");
        return next;
      },
      { replace: true },
    );
  }, [setParams]);

  if (callId) return <CallDetailView key={callId} callId={callId} onBack={() => setParam("call", "")} />;
  return (
    <CallsList
      outcome={params.get("outcome") ?? ""}
      activeOnly={params.get("active") === "true"}
      setParam={setParam}
      clearFilters={clearFilters}
    />
  );
}

function CallsList({
  outcome,
  activeOnly,
  setParam,
  clearFilters,
}: {
  outcome: string;
  activeOnly: boolean;
  setParam: (key: string, value: string) => void;
  clearFilters: () => void;
}) {
  const listParams = buildCallListParams(outcome, activeOnly);
  const list = useQuery({
    queryKey: qk.calls.list(listParams),
    queryFn: ({ signal }) => api.listCalls(listParams, signal),
  });
  const anyFilter = Boolean(outcome || activeOnly);

  return (
    <>
      <PageHeader
        title="Calls"
        subtitle="Newest first. Updates arrive live; opening a call is recorded in the audit log."
        actions={
          <Button size="sm" onClick={() => void list.refetch()} disabled={list.isFetching} aria-label="Refresh calls">
            <RefreshCw size={14} className={list.isFetching ? "animate-spin" : undefined} aria-hidden /> Refresh
          </Button>
        }
      />
      <Panel flush>
        <form
          role="search"
          aria-label="Call filters"
          className="flex flex-wrap items-end gap-3 border-b border-line px-4 py-3"
          onSubmit={(event) => event.preventDefault()}
        >
          <div>
            <label className="label" htmlFor="call-outcome">
              Outcome
            </label>
            <select id="call-outcome" className="input" value={outcome} onChange={(e) => setParam("outcome", e.target.value)}>
              <option value="">All outcomes</option>
              {CALL_OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {humanize(o)}
                </option>
              ))}
            </select>
          </div>
          <label className="flex cursor-pointer items-center gap-2 pb-1.5 text-sm text-ink">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[#7A5A40]"
              checked={activeOnly}
              onChange={(e) => setParam("active", e.target.checked ? "true" : "")}
            />
            Active calls only
          </label>
          {anyFilter ? (
            <Button size="sm" variant="ghost" onClick={clearFilters}>
              <X size={14} aria-hidden /> Clear filters
            </Button>
          ) : null}
          <p className="ml-auto self-center text-xs text-ink-soft" aria-live="polite">
            {list.data ? `${list.data.items.length} calls` : ""}
          </p>
        </form>
        <DataTable
          caption="Calls"
          columns={columns}
          rows={list.data?.items}
          rowKey={(c) => c.call_id}
          onRowClick={(c) => setParam("call", c.call_id)}
          isLoading={list.isPending}
          error={list.error}
          onRetry={() => void list.refetch()}
          emptyTitle={anyFilter ? "No calls match these filters" : "No calls yet"}
          emptyHint={anyFilter ? "Try another outcome or switch off the active filter." : "Calls appear here as soon as the voice runtime registers them."}
        />
      </Panel>
    </>
  );
}

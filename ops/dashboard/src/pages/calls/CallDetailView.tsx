import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Eye, EyeOff, RefreshCw, ShieldCheck } from "lucide-react";
import { api, qk, type TurnSummary } from "../../api";
import {
  Button,
  DataTable,
  ErrorState,
  LoadingState,
  MaskedNumber,
  PageHeader,
  Panel,
  PriorityBadge,
  StatusChip,
  type Column,
} from "../../components";
import { useReveal } from "../../hooks/useReveal";
import { formatDateTime, formatDuration, humanize, secondsBetween } from "../../lib/format";
import { formatLatency, isActiveCall, outcomeLabel, yesNo } from "./callLogic";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="mt-0.5 break-words text-[13px] text-ink">{children}</dd>
    </div>
  );
}

const turnColumns: Column<TurnSummary>[] = [
  { key: "idx", header: "#", width: "2.5rem", cell: (t) => <span className="tabular-nums">{t.turn_index}</span> },
  { key: "path", header: "Path", cell: (t) => <span className="text-xs">{humanize(t.path)}</span> },
  { key: "tier", header: "Tier", cell: (t) => <span className="text-xs">{t.tier ? humanize(t.tier) : "—"}</span> },
  {
    key: "kb",
    header: "KB ids",
    cell: (t) =>
      t.kb_ids && t.kb_ids.length > 0 ? (
        <span className="break-all font-mono text-[11px]">{t.kb_ids.join(", ")}</span>
      ) : (
        <span className="text-ink-faint">—</span>
      ),
  },
  {
    key: "flags",
    header: "Validator flags",
    cell: (t) =>
      t.validator_flags && t.validator_flags.length > 0 ? (
        <span className="flex flex-wrap gap-1">
          {t.validator_flags.map((flag) => (
            <span key={flag} className="rounded border border-[#E8D3B1] bg-[#F5E9D8] px-1 py-0.5 text-[11px] text-[#80551F]">
              {flag}
            </span>
          ))}
        </span>
      ) : (
        <span className="text-ink-faint">—</span>
      ),
  },
  {
    key: "latency",
    header: "Latency ms",
    cell: (t) => (
      <span className="font-mono text-[11px]" title={JSON.stringify(t.latency_ms ?? {})}>
        {formatLatency(t.latency_ms)}
      </span>
    ),
  },
  {
    key: "cached",
    header: "Cached tok",
    align: "right",
    cell: (t) => <span className="tabular-nums">{t.cached_tokens ?? "—"}</span>,
  },
  {
    key: "priority",
    header: "Priority",
    cell: (t) =>
      t.priority ? (
        <span className="inline-flex items-center gap-1" title={t.priority_reason ?? undefined}>
          <PriorityBadge priority={t.priority} />
          {t.rule_id ? <span className="font-mono text-[10px] text-ink-faint">{t.rule_id}</span> : null}
        </span>
      ) : (
        <span className="text-ink-faint">—</span>
      ),
  },
  {
    key: "user",
    header: "Caller (redacted)",
    className: "min-w-[14rem]",
    cell: (t) => <span className="whitespace-pre-wrap text-[13px]">{t.user_text_redacted || <span className="text-ink-faint">(empty)</span>}</span>,
  },
  {
    key: "assistant",
    header: "Assistant",
    className: "min-w-[16rem]",
    cell: (t) => <span className="whitespace-pre-wrap text-[13px]">{t.assistant_text || <span className="text-ink-faint">(empty)</span>}</span>,
  },
];

export interface CallDetailViewProps {
  callId: string;
  onBack: () => void;
}

/**
 * Call detail with the turns table. GET /v1/calls/{id} writes a `transcript_viewed` audit row on every request, so
 * the query never refetches on focus or reconnect; an explicit Refresh button is offered instead (live calls get new
 * turns without any automatic refetch).
 */
export function CallDetailView({ callId, onBack }: CallDetailViewProps) {
  const detail = useQuery({
    queryKey: qk.calls.detail(callId, false),
    queryFn: ({ signal }) => api.getCall(callId, {}, signal),
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const call = detail.data?.call;
  const turns = detail.data?.turns;
  // L12: the revealed copy is one explicit fetch (no SSE / focus refetch) and leaves the cache on Hide or unmount.
  const reveal = useReveal(qk.calls.detail(callId, true), (signal) => api.getCall(callId, { reveal: true }, signal));
  const revealed = reveal.revealed;
  const revealedCopy = reveal.data;
  const revealActive = revealed && !!revealedCopy;
  const callerNumber = revealedCopy?.call.caller_number ?? call?.caller_number;

  return (
    <>
      <PageHeader
        title={`Call ${callId}`}
        subtitle="Opening a call is recorded in the audit log."
        actions={
          <>
            <Button size="sm" onClick={onBack}>
              <ArrowLeft size={14} aria-hidden /> All calls
            </Button>
            <Button size="sm" onClick={() => void detail.refetch()} disabled={detail.isFetching}>
              <RefreshCw size={14} className={detail.isFetching ? "animate-spin" : undefined} aria-hidden /> Refresh
            </Button>
          </>
        }
      />
      {detail.isError && !call ? (
        <Panel>
          <ErrorState error={detail.error} title="Could not load the call" onRetry={() => void detail.refetch()} />
        </Panel>
      ) : !call ? (
        <Panel>
          <LoadingState label="Loading call…" variant="skeleton" rows={5} />
        </Panel>
      ) : (
        <>
          <Panel
            className="mb-4"
            title="Call"
            actions={
              <Button
                size="sm"
                onClick={reveal.toggle}
                aria-pressed={revealed}
                disabled={!call.caller_number || reveal.pending}
              >
                {revealed ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}
                {revealed ? "Hide number" : "Reveal number"}
              </Button>
            }
          >
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
              <Fact label="Caller number">
                <MaskedNumber value={callerNumber} revealed={revealActive} />
              </Fact>
              <Fact label="Channel">{call.channel}</Fact>
              <Fact label="Language">{call.lang}</Fact>
              <Fact label="Outcome">
                {call.outcome ? <StatusChip status={call.outcome} /> : <StatusChip status={isActiveCall(call) ? "in_progress" : null} label={outcomeLabel(call)} />}
              </Fact>
              <Fact label="Started">{formatDateTime(call.started_at)}</Fact>
              <Fact label="Ended">{call.ended_at ? formatDateTime(call.ended_at) : "Still running"}</Fact>
              <Fact label="Duration">{call.ended_at ? formatDuration(secondsBetween(call.started_at, call.ended_at)) : "—"}</Fact>
              <Fact label="AI resolved">{yesNo(call.ai_resolved)}</Fact>
              <Fact label="Turns">{call.turns_count}</Fact>
              <Fact label="KB version">
                <span className="font-mono text-xs">{call.kb_version || "—"}</span>
              </Fact>
            </dl>
            {revealActive ? (
              <p className="mt-3 inline-flex items-center gap-1 rounded bg-[#F5E9D8] px-2 py-1 text-xs text-[#80551F]" role="status">
                <ShieldCheck size={13} aria-hidden /> Number revealed, access recorded in the audit log.
              </p>
            ) : null}
            {reveal.error ? (
              <p role="alert" className="mt-2 text-xs text-p1">
                Could not reveal the number: {reveal.error instanceof Error ? reveal.error.message : "request failed"}
              </p>
            ) : null}
          </Panel>
          <Panel title={`Turns (${turns?.length ?? 0})`} flush>
            <DataTable
              caption="Turns of this call"
              columns={turnColumns}
              rows={turns}
              rowKey={(t) => String(t.turn_index)}
              emptyTitle="No turns recorded"
              emptyHint={isActiveCall(call) ? "The call is still running. Use Refresh to load new turns." : "The voice runtime stored no turns for this call."}
            />
          </Panel>
        </>
      )}
    </>
  );
}

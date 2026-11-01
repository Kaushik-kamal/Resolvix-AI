import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, qk } from "../../api";
import { EmptyState, ErrorState, LoadingState } from "../../components";
import { humanize } from "../../lib/format";

/**
 * Transcript of the ticket's call. Collapsed by default: the call detail endpoint writes a `transcript_viewed` audit
 * row on every request, so it is only fetched after the user opens this section (and not refetched on focus).
 */
export function TicketTranscript({ callId }: { callId: string | null | undefined }) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: qk.calls.detail(callId ?? "", false),
    queryFn: ({ signal }) => api.getCall(callId ?? "", {}, signal),
    enabled: open && Boolean(callId),
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  if (!callId) {
    return <p className="text-xs text-ink-faint">No call is linked to this ticket, so there is no transcript.</p>;
  }

  const turns = detail.data?.turns ?? [];
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
          {open ? "Hide transcript" : "Show transcript"}
        </button>
        <Link to={`/calls?call=${encodeURIComponent(callId)}`} className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
          Open call {callId} <ExternalLink size={12} aria-hidden />
        </Link>
      </div>
      {!open ? (
        <p className="mt-1.5 text-xs text-ink-faint">Opening the transcript is recorded in the audit log.</p>
      ) : detail.isError ? (
        <ErrorState error={detail.error} title="Could not load the transcript" onRetry={() => void detail.refetch()} className="p-4" />
      ) : detail.isPending ? (
        <LoadingState label="Loading transcript…" variant="skeleton" rows={3} />
      ) : turns.length === 0 ? (
        <EmptyState title="No turns recorded" hint="The call has no stored turns yet." className="p-4" />
      ) : (
        <ol className="mt-2 space-y-2.5" aria-label="Call transcript">
          {turns.map((turn) => (
            <li key={turn.turn_index} className="rounded-md border border-line bg-surface p-2.5 text-[13px]">
              <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-faint">
                <span className="font-semibold text-ink-soft">Turn {turn.turn_index}</span>
                <span className="rounded bg-bg px-1.5 py-0.5">path: {humanize(turn.path)}</span>
                {turn.tier ? <span className="rounded bg-bg px-1.5 py-0.5">tier: {humanize(turn.tier)}</span> : null}
              </div>
              <p className="whitespace-pre-wrap">
                <span className="mr-1 font-semibold text-accent-slate">Caller:</span>
                {turn.user_text_redacted || <span className="text-ink-faint">(empty)</span>}
              </p>
              <p className="mt-1 whitespace-pre-wrap">
                <span className="mr-1 font-semibold text-accent">Assistant:</span>
                {turn.assistant_text || <span className="text-ink-faint">(empty)</span>}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

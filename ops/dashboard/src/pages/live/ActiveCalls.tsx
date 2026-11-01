import clsx from "clsx";
import { Globe, Phone, PhoneCall, TestTube } from "lucide-react";
import { Link } from "react-router-dom";
import type { CallSummary, CallTurnEvent } from "../../api/extra";
import { EmptyState, ErrorState, LoadingState, MaskedNumber, PriorityBadge } from "../../components";
import { useNow } from "../../hooks/useNow";
import { formatDuration, humanize, secondsBetween } from "../../lib/format";

const CHANNEL_ICON = { pstn: Phone, web: Globe, test: TestTube } as const;

function ActiveCallCard({
  call,
  lastTurn: streamTurn,
  projector = false,
}: {
  call: CallSummary;
  lastTurn?: CallTurnEvent;
  projector?: boolean;
}) {
  // the stream wins; after a reload the REST list carries the latest stored turn
  const lastTurn = streamTurn ?? (call.last_turn ? { path: call.last_turn.path, tier: call.last_turn.tier, priority: null, turns_count: call.turns_count } : undefined);
  const now = useNow(1000);
  const Icon = CHANNEL_ICON[call.channel] ?? Phone;
  return (
    <Link
      to={`/calls?call=${encodeURIComponent(call.call_id)}`}
      className="block rounded-md border border-line bg-surface p-2.5 shadow-sm hover:shadow-md"
      data-testid={`active-call-${call.call_id}`}
    >
      <div className="flex items-center gap-2">
        <span className="relative flex h-2 w-2" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#7FB98A] opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-[#4F9A5F]" />
        </span>
        <Icon size={14} className="text-ink-faint" aria-label={call.channel} />
        <MaskedNumber value={call.caller_number} className={projector ? "text-lg font-semibold" : "text-[13px] font-semibold"} />
        <span className={clsx("ml-auto font-mono tabular-nums text-ink", projector ? "text-lg" : "text-sm")} data-testid="call-duration">
          {formatDuration(secondsBetween(call.started_at, now))}
        </span>
      </div>
      <div className={clsx("mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-ink-soft", projector ? "text-base" : "text-xs")}>
        <span className="rounded bg-bg px-1.5 py-0.5">{call.lang}</span>
        {lastTurn ? (
          <>
            <span className="rounded bg-[#E3EAEE] px-1.5 py-0.5 text-[#40596A]">{humanize(lastTurn.path)}</span>
            {lastTurn.tier ? <span className="rounded bg-bg px-1.5 py-0.5">{humanize(lastTurn.tier)}</span> : null}
            {lastTurn.priority ? <PriorityBadge priority={lastTurn.priority} /> : null}
          </>
        ) : (
          <span className="text-ink-faint">{call.turns_count > 0 ? "last turn: waiting for next" : "no turn yet"}</span>
        )}
        <span className="ml-auto">
          {Math.max(call.turns_count, lastTurn?.turns_count ?? 0)} turn
          {Math.max(call.turns_count, lastTurn?.turns_count ?? 0) === 1 ? "" : "s"}
        </span>
      </div>
    </Link>
  );
}

export interface ActiveCallsProps {
  calls: CallSummary[];
  lastTurns: Record<string, CallTurnEvent>;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  /** staff sessions only see calls linked to a ticket of their department and get no call.* stream events */
  isStaff?: boolean;
  /** projector mode: bigger type */
  projector?: boolean;
}

/** Left column of the live board: calls without ended_at, newest first, duration ticking every second. */
export function ActiveCalls({ calls, lastTurns, isLoading, error, onRetry, isStaff = false, projector = false }: ActiveCallsProps) {
  if (error) return <ErrorState title="Could not load active calls" error={error} onRetry={onRetry} />;
  if (isLoading) return <LoadingState variant="skeleton" rows={3} label="Loading active calls" />;
  if (calls.length === 0 && isStaff) {
    return (
      <EmptyState
        icon={<PhoneCall size={26} aria-hidden />}
        title="Live calls are visible to admins"
        hint="Calls appear here once they produce a ticket for your department. This list refreshes about once a minute; your tickets update live on the right."
        className={projector ? "[&_p]:text-base" : undefined}
      />
    );
  }
  if (calls.length === 0) {
    return (
      <EmptyState
        icon={<PhoneCall size={26} aria-hidden />}
        title="No active calls"
        hint="New calls appear here the moment they start."
      />
    );
  }
  return (
    <>
      {isStaff ? (
        <p className="border-b border-line px-3 py-1.5 text-[11px] text-ink-faint" data-testid="staff-calls-note">
          Only calls linked to a ticket of your department; refreshed about once a minute.
        </p>
      ) : null}
      <ul className="space-y-2 p-3">
        {calls.map((call) => (
          <li key={call.call_id}>
            <ActiveCallCard call={call} lastTurn={lastTurns[call.call_id]} projector={projector} />
          </li>
        ))}
      </ul>
    </>
  );
}

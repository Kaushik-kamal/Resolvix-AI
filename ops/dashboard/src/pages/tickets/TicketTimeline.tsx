import { ArrowRight, FileText, MessageSquare, PhoneForwarded, PhoneIncoming, PhoneOff, RefreshCw, StickyNote } from "lucide-react";
import type { ReactNode } from "react";
import type { TicketEventRow } from "../../api/extra";
import { EmptyState, ErrorState, LoadingState, ModeBadge, RelativeTime, StatusChip } from "../../components";
import { formatDateTimeSeconds, humanize } from "../../lib/format";
import { payloadEntries, safePayloadValue, sortEvents } from "./ticketLogic";

const SMS_KINDS = new Set(["sms_queued", "sms_sent", "sms_failed", "sms_suppressed"]);

const TITLES: Record<string, string> = {
  transfer_attempted: "Transfer attempted",
  transfer_connected: "Transfer connected",
  transfer_failed: "Transfer failed",
  sms_queued: "SMS queued",
  sms_sent: "SMS sent",
  sms_failed: "SMS failed",
  sms_suppressed: "SMS suppressed",
  status_changed: "Status changed",
  note_added: "Note added",
  callback_scheduled: "Callback scheduled",
  brief_pushed: "Brief pushed to the department",
};

function iconFor(kind: string): ReactNode {
  const props = { size: 14, "aria-hidden": true } as const;
  if (kind === "transfer_attempted") return <PhoneForwarded {...props} />;
  if (kind === "transfer_connected") return <PhoneIncoming {...props} />;
  if (kind === "transfer_failed") return <PhoneOff {...props} />;
  if (SMS_KINDS.has(kind)) return <MessageSquare {...props} />;
  if (kind === "status_changed") return <RefreshCw {...props} />;
  if (kind === "note_added") return <StickyNote {...props} />;
  return <FileText {...props} />;
}

/** "live" | "mock" | null: the mode of an sms_* event payload (null when A did not send one). */
function smsMode(event: TicketEventRow): string | null {
  const mode = (event.payload as Record<string, unknown> | null | undefined)?.mode;
  return typeof mode === "string" && mode ? mode : null;
}

/**
 * Event title. An sms_sent row is only "SMS sent" in live mode; a mock row (nothing left the building) reads
 * "SMS recorded (mock)", and one without a mode "SMS recorded (mode unknown)" (L7).
 */
export function titleFor(event: TicketEventRow): string {
  if (event.kind === "sms_sent") {
    const mode = smsMode(event);
    if (mode === "live") return "SMS sent";
    if (mode === "mock") return "SMS recorded (mock)";
    return "SMS recorded (mode unknown)";
  }
  return TITLES[event.kind] ?? humanize(event.kind);
}

/** Success green only for events that really happened: a connected transfer or a LIVE sms_sent. */
export function toneFor(event: TicketEventRow): string {
  const { kind } = event;
  if (kind === "transfer_failed" || kind === "sms_failed") return "text-p1 border-p1/40";
  if (kind === "transfer_connected" || (kind === "sms_sent" && smsMode(event) === "live")) {
    return "text-[#3F6B49] border-[#C7DBCC]";
  }
  return "text-ink-soft border-line";
}

function EventBody({ event }: { event: TicketEventRow }) {
  const payload = (event.payload ?? {}) as Record<string, unknown>;
  if (SMS_KINDS.has(event.kind)) {
    const status = typeof payload.status === "string" ? payload.status : event.kind.replace("sms_", "");
    const rest = payloadEntries(payload, ["mode", "status", "template_id", "to", "reason"]);
    return (
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-soft">
        <ModeBadge mode={typeof payload.mode === "string" ? payload.mode : null} />
        {event.kind === "sms_sent" && smsMode(event) !== "live" ? (
          <StatusChip status={status} tone="neutral" label={status === "sent" ? "recorded" : undefined} />
        ) : (
          <StatusChip status={status} />
        )}
        {payload.template_id ? <span>template <code className="font-mono">{String(payload.template_id)}</code></span> : null}
        {payload.to ? (
          <span>
            to <span className="font-mono">{safePayloadValue(payload.to)}</span>
          </span>
        ) : null}
        {payload.reason ? <span>reason: {String(payload.reason)}</span> : null}
        {rest.map(([key, value]) => (
          <span key={key}>
            {key}: {value}
          </span>
        ))}
      </div>
    );
  }
  if (event.kind === "status_changed") {
    return (
      <div className="mt-1 flex items-center gap-1.5 text-xs">
        <StatusChip status={String(payload.old_status ?? "")} />
        <ArrowRight size={12} className="text-ink-faint" aria-hidden />
        <StatusChip status={String(payload.new_status ?? "")} />
      </div>
    );
  }
  if (event.kind === "note_added") {
    return <p className="mt-1 whitespace-pre-wrap text-xs text-ink">{String(payload.note ?? "")}</p>;
  }
  const entries = payloadEntries(payload);
  if (entries.length === 0) return null;
  return (
    <dl className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-ink-soft">
      {entries.map(([key, value]) => (
        <div key={key} className="flex gap-1">
          <dt className="text-ink-faint">{key}:</dt>
          <dd className="break-all">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface TicketTimelineProps {
  events: TicketEventRow[] | undefined;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
}

/** Events of one ticket, oldest first so the newest sits at the bottom. */
export function TicketTimeline({ events, isLoading, error, onRetry }: TicketTimelineProps) {
  if (error) return <ErrorState error={error} title="Could not load the timeline" onRetry={onRetry} className="p-4" />;
  if (isLoading && !events) return <LoadingState label="Loading timeline…" variant="skeleton" rows={2} />;
  if (!events || events.length === 0) {
    return <EmptyState title="No events yet" hint="Transfers, SMS messages, status changes and notes appear here." className="p-4" />;
  }
  return (
    <ol className="space-y-2" aria-label="Ticket events">
      {sortEvents(events).map((event, index) => (
        <li key={`${event.at}-${event.kind}-${index}`} className="flex gap-2.5" data-event-kind={event.kind}>
          <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-surface ${toneFor(event)}`}>
            {iconFor(event.kind)}
          </span>
          <div className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5">
            <div className="flex flex-wrap items-baseline justify-between gap-x-2">
              <span className="text-[13px] font-medium text-ink">{titleFor(event)}</span>
              <span className="text-xs text-ink-faint" title={formatDateTimeSeconds(event.at)}>
                {event.actor ? <span className="mr-1.5">{event.actor}</span> : null}
                <RelativeTime value={event.at} tickMs={15_000} />
              </span>
            </div>
            <EventBody event={event} />
          </div>
        </li>
      ))}
    </ol>
  );
}

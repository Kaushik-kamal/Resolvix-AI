import clsx from "clsx";
import { Clock, User } from "lucide-react";
import { Link } from "react-router-dom";
import type { Priority, TicketRow } from "../../api/extra";
import { PriorityBadge, RelativeTime, StatusChip } from "../../components";
import { useNow } from "../../hooks/useNow";
import { formatDuration, humanize, secondsBetween } from "../../lib/format";
import { PROJECTOR_CLASSES as PC } from "../../lib/projector";
import { slaFor } from "../../lib/sla";

const SLA_CLASSES = {
  ok: "text-ink-soft",
  warn: "font-semibold text-[#9A6A22]",
  breached: "font-semibold text-p1",
} as const;

export interface TicketCardProps {
  ticket: TicketRow;
  flashing?: boolean;
  /** projector mode: about 1.4x type */
  projector?: boolean;
}

/** SLA-ish timer text: "12m 03s left" before the target, "3m 10s over" after it. */
export function SlaTimer({ priority, createdAt }: { priority: Priority; createdAt: string }) {
  const now = useNow(1000);
  const sla = slaFor(priority, secondsBetween(createdAt, now));
  const text =
    sla.state === "breached"
      ? `${formatDuration(-sla.remainingSeconds)} over`
      : `${formatDuration(sla.remainingSeconds)} left`;
  return (
    <span
      className={clsx("inline-flex items-center gap-1 tabular-nums", SLA_CLASSES[sla.state])}
      title={`SLA target ${formatDuration(sla.targetMinutes * 60)} for ${priority}`}
      data-sla={sla.state}
    >
      <Clock size={12} aria-hidden />
      {text}
    </span>
  );
}

export function TicketCard({ ticket, flashing, projector = false }: TicketCardProps) {
  return (
    <Link
      to={`/tickets?ticket=${encodeURIComponent(ticket.ticket_id)}`}
      className={clsx(
        "block min-w-0 rounded-md border bg-surface p-2.5 shadow-sm transition-shadow hover:shadow-md",
        ticket.priority === "P1" ? "border-p1/50" : "border-line",
        flashing && "animate-flash",
      )}
      data-testid={`ticket-card-${ticket.ticket_id}`}
      data-flashing={flashing ? "true" : undefined}
      data-projector={projector ? "true" : undefined}
    >
      <div className="mb-1 flex items-center gap-2">
        <PriorityBadge priority={ticket.priority} />
        <span className={clsx("font-mono font-semibold text-ink", projector ? PC.cardId : PC.cardIdNormal)}>{ticket.ticket_id}</span>
        <span className={clsx("ml-auto text-ink-faint", projector ? PC.cardMeta : PC.cardMetaNormal)}>
          <RelativeTime value={ticket.created_at} tickMs={15_000} />
        </span>
      </div>
      <p className={clsx("line-clamp-2 break-words leading-snug text-ink", projector ? PC.cardSummary : PC.cardSummaryNormal)}>
        {ticket.summary}
      </p>
      <div className={clsx("mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-ink-soft", projector ? PC.cardMeta : PC.cardMetaNormal)}>
        <span className="rounded bg-bg px-1.5 py-0.5">{humanize(ticket.department)}</span>
        {ticket.status !== "open" ? <StatusChip status={ticket.status} /> : null}
        {ticket.assignee ? (
          <span className="inline-flex items-center gap-1">
            <User size={12} aria-hidden />
            {ticket.assignee}
          </span>
        ) : null}
        <span className="ml-auto whitespace-nowrap">
          <SlaTimer priority={ticket.priority} createdAt={ticket.created_at} />
        </span>
      </div>
    </Link>
  );
}

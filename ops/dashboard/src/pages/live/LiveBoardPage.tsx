import clsx from "clsx";
import { CheckCircle2, Info, Monitor } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAlerts } from "../../alerts/AlertContext";
import type { Priority, TicketRow } from "../../api/extra";
import { useSessionUser } from "../../auth/AuthContext";
import { Button, EmptyState, ErrorState, LoadingState, PageHeader, Panel, PriorityBadge } from "../../components";
import { formatCount, humanize } from "../../lib/format";
import { PROJECTOR_CLASSES as PC, useProjectorMode } from "../../lib/projector";
import { SLA_TARGET_MINUTES } from "../../lib/sla";
import { useEventStream } from "../../stream/EventStreamContext";
import { ActiveCalls } from "./ActiveCalls";
import { TicketCard } from "./TicketCard";
import { useLiveBoardData, type BoardCounts } from "./useLiveBoardData";

const COLUMNS: { priority: Priority; title: string; accent: string }[] = [
  { priority: "P1", title: "P1 Critical", accent: "border-t-p1" },
  { priority: "P2", title: "P2 High", accent: "border-t-p2" },
  { priority: "P3", title: "P3 Normal", accent: "border-t-p3" },
];

function Stat({
  label,
  value,
  hint,
  tone,
  projector,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "alert";
  projector?: boolean;
}) {
  return (
    <div className="card min-w-0 px-4 py-3" data-testid={`stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className={clsx("font-medium uppercase tracking-wide text-ink-soft", projector ? PC.statLabel : PC.statLabelNormal)}>
        {label}
      </div>
      <div
        className={clsx(
          "mt-0.5 font-semibold tabular-nums",
          projector ? PC.statValue : PC.statValueNormal,
          tone === "alert" ? "text-p1" : "text-ink",
        )}
      >
        {value}
      </div>
      {hint ? <div className={clsx("text-ink-faint", projector ? PC.statHint : PC.statHintNormal)}>{hint}</div> : null}
    </div>
  );
}

function CountsRow({
  counts,
  loading,
  error,
  onRetry,
  isStaff,
  department,
  projector,
}: {
  counts: BoardCounts;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  isStaff: boolean;
  department: string | null;
  projector: boolean;
}) {
  if (error) return <ErrorState title="Could not load today's counts" error={error} onRetry={onRetry} className="card py-4" />;
  const v = (n: number) => (loading ? "…" : formatCount(n));
  const p1 = (
    <Stat
      label="P1 open"
      value={v(counts.p1Open)}
      hint={isStaff ? "your department, open or in progress" : "open or in progress"}
      tone={counts.p1Open > 0 ? "alert" : undefined}
      projector={projector}
    />
  );
  if (isStaff) {
    // M4: the other three stats need every call, but staff only see calls linked to tickets of their department.
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(180px,280px)_minmax(0,1fr)]" aria-live="polite" data-testid="counts-row">
        {p1}
        <div
          className={clsx("card flex items-start gap-2 px-4 py-3 text-ink-soft", projector ? "text-base" : "text-xs")}
          data-testid="staff-counts-note"
        >
          <Info size={projector ? 22 : 16} className="mt-0.5 shrink-0 text-ink-faint" aria-hidden />
          <p>
            Call statistics (calls today, answered by AI, escalated) cover every call and are shown to admins only. As
            staff you see the tickets of {department ? humanize(department) : "your department"}; the P1 count is for your
            department only.
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-live="polite" data-testid="counts-row">
      <Stat label="Calls today" value={v(counts.callsToday)} hint="since 00:00 IST" projector={projector} />
      <Stat label="Answered by AI" value={v(counts.answeredByAi)} hint="resolved without a human" projector={projector} />
      <Stat label="Escalated" value={v(counts.escalated)} hint="escalated, transferred or emergency" projector={projector} />
      {p1}
    </div>
  );
}

function TicketColumn({
  priority,
  title,
  accent,
  tickets,
  loading,
  isFlashing,
  projector,
}: {
  priority: Priority;
  title: string;
  accent: string;
  tickets: TicketRow[];
  loading: boolean;
  isFlashing: (id: string) => boolean;
  projector: boolean;
}) {
  return (
    <section
      className={clsx("flex min-h-0 min-w-0 flex-col rounded-lg border border-t-4 border-line bg-[#EFE9E2]/60", accent)}
      aria-label={title}
      data-testid={`column-${priority}`}
    >
      <header className="flex items-center gap-2 px-3 py-2">
        <PriorityBadge priority={priority} />
        <h3 className={clsx("font-semibold text-ink", projector ? PC.columnTitle : PC.columnTitleNormal)}>{title}</h3>
        <span
          className={clsx("ml-auto text-ink-soft", projector ? PC.cardMeta : PC.cardMetaNormal)}
          title={`SLA target ${SLA_TARGET_MINUTES[priority]} min`}
        >
          {loading ? "…" : tickets.length}
        </span>
      </header>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-2 pb-2 [max-height:calc(100vh-17rem)]">
        {loading ? (
          <LoadingState variant="skeleton" rows={2} label={`Loading ${priority} tickets`} className="p-0" />
        ) : tickets.length === 0 ? (
          <EmptyState
            icon={<CheckCircle2 size={22} aria-hidden />}
            title={`No open ${priority} tickets`}
            className="py-6"
          />
        ) : (
          tickets.map((ticket) => (
            <TicketCard
              key={ticket.ticket_id}
              ticket={ticket}
              flashing={isFlashing(ticket.ticket_id)}
              projector={projector}
            />
          ))
        )}
      </div>
    </section>
  );
}

/** "/": live board. Active calls on the left, P1/P2/P3 ticket columns on the right, counts on top. */
export default function LiveBoardPage() {
  const data = useLiveBoardData();
  const { lastTurns } = useEventStream();
  const { isFlashing } = useAlerts();
  const [projector, , toggleProjector] = useProjectorMode();
  const me = useSessionUser();
  const p4Open = data.tickets.filter((t) => t.priority === "P4").length;

  return (
    <>
      <PageHeader
        title="Live board"
        subtitle="Updates arrive over the live stream; no refresh needed."
        actions={
          <Button
            size="sm"
            variant={projector ? "primary" : "secondary"}
            onClick={toggleProjector}
            aria-pressed={projector}
            title="Larger type for a room display"
          >
            <Monitor size={14} aria-hidden /> Projector
          </Button>
        }
      />
      <div className={clsx("space-y-4", PC.root)} data-projector={projector ? "true" : "false"} data-testid="live-board">
        <CountsRow
          counts={data.counts}
          loading={data.countsLoading}
          error={data.countsError}
          onRetry={data.refetchCounts}
          isStaff={data.isStaff}
          department={me?.department ?? null}
          projector={projector}
        />
        <div
          className={clsx(
            "grid gap-4",
            projector
              ? "[grid-template-columns:minmax(220px,280px)_minmax(0,1fr)]"
              : "[grid-template-columns:minmax(280px,340px)_minmax(0,1fr)]",
          )}
          data-testid="board-grid"
        >
          <Panel title="Active calls" flush className="min-w-0 self-start">
            <ActiveCalls
              calls={data.activeCalls}
              lastTurns={lastTurns}
              isLoading={data.callsLoading}
              error={data.callsError}
              onRetry={data.refetchCalls}
              isStaff={data.isStaff}
              projector={projector}
            />
          </Panel>
          <div className="min-w-0">
            {data.ticketsError ? (
              <div className="card">
                <ErrorState title="Could not load tickets" error={data.ticketsError} onRetry={data.refetchTickets} />
              </div>
            ) : (
              <>
                <div className="grid grid-cols-3 gap-3" data-testid="ticket-columns">
                  {COLUMNS.map((col) => (
                    <TicketColumn
                      key={col.priority}
                      {...col}
                      tickets={data.columns[col.priority]}
                      loading={data.ticketsLoading}
                      isFlashing={isFlashing}
                      projector={projector}
                    />
                  ))}
                </div>
                {p4Open > 0 ? (
                  <p className={clsx("mt-2 text-ink-soft", projector ? "text-base" : "text-xs")}>
                    {p4Open} open P4 ticket{p4Open === 1 ? "" : "s"} not shown here.{" "}
                    <Link className="underline" to="/tickets">
                      Open the ticket list
                    </Link>
                  </p>
                ) : null}
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

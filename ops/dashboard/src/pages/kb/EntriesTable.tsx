import clsx from "clsx";
import { AlertTriangle, CalendarClock, Pencil, ShieldAlert } from "lucide-react";
import type { KBEntry } from "../../api/types";
import { Button, DataTable, StatusChip, type Column } from "../../components";
import { formatDate, humanize } from "../../lib/format";
import { expiryInfo, expiryLabel } from "./kbModel";

export type KbStatus = "draft" | "approved" | "archived";

export interface KbRow {
  entry: KBEntry;
  /** flagged_ids includes the id (or meta says so) */
  flagged: boolean;
  updatedAt?: string;
}

export function FlaggedBadge({ className }: { className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[#EBC4B6] bg-[#F6E1D9] px-2 py-0.5 text-xs font-semibold text-[#8D3C21]",
        className,
      )}
      title="Flagged by the injection scan: it cannot be approved until its text is edited and saved again."
    >
      <ShieldAlert size={12} aria-hidden /> Flagged
    </span>
  );
}

/** valid_until cell: the date plus a warning when the entry expires in under 14 days (IST) or already expired. */
export function ValidUntilCell({ value, now }: { value: string | null | undefined; now: Date }) {
  if (!value) return <span className="text-ink-faint">No expiry</span>;
  const info = expiryInfo(value, now);
  const warn = info.kind === "soon" || info.kind === "expired";
  return (
    <div className="whitespace-nowrap">
      <div className="tabular-nums">{formatDate(`${value}T00:00:00+05:30`)}</div>
      {warn ? (
        <div
          data-expiry={info.kind}
          className={clsx(
            "mt-0.5 inline-flex items-center gap-1 text-xs font-medium",
            info.kind === "expired" ? "text-[#8D3C21]" : "text-[#80551F]",
          )}
        >
          {info.kind === "expired" ? <AlertTriangle size={12} aria-hidden /> : <CalendarClock size={12} aria-hidden />}
          {expiryLabel(info)}
        </div>
      ) : null}
    </div>
  );
}

export interface EntriesTableProps {
  rows: KbRow[] | undefined;
  isAdmin: boolean;
  now: Date;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  /** id of the entry whose status request is in flight */
  busyId?: string | null;
  onEdit: (row: KbRow) => void;
  onSetStatus: (row: KbRow, status: KbStatus) => void;
  emptyTitle?: string;
  emptyHint?: string;
}

export function EntriesTable({
  rows,
  isAdmin,
  now,
  isLoading,
  error,
  onRetry,
  busyId,
  onEdit,
  onSetStatus,
  emptyTitle,
  emptyHint,
}: EntriesTableProps) {
  const columns: Column<KbRow>[] = [
    {
      key: "id",
      header: "ID",
      width: "6.5rem",
      sortValue: (r) => r.entry.id,
      cell: (r) => <span className="font-mono text-xs font-semibold">{r.entry.id}</span>,
    },
    {
      key: "question",
      header: "Question / answer",
      cell: (r) => (
        <div className="max-w-[28rem]">
          <div className="line-clamp-2 break-words font-medium text-ink">{r.entry.question_variants[0]}</div>
          <div className="line-clamp-1 break-words text-xs text-ink-soft">{r.entry.answer_en}</div>
          {r.entry.is_faq ? <span className="mt-0.5 inline-block text-[11px] font-semibold text-accent">FAQ</span> : null}
        </div>
      ),
    },
    {
      key: "department",
      header: "Department",
      width: "8rem",
      sortValue: (r) => r.entry.department,
      cell: (r) => humanize(r.entry.department),
    },
    {
      key: "status",
      header: "Status",
      width: "9rem",
      sortValue: (r) => r.entry.status ?? "",
      cell: (r) => (
        <div className="flex flex-col items-start gap-1">
          <StatusChip status={r.entry.status ?? "approved"} />
          {r.flagged ? <FlaggedBadge /> : null}
        </div>
      ),
    },
    {
      key: "valid_until",
      header: "Valid until",
      width: "9rem",
      sortValue: (r) => r.entry.valid_until ?? "9999-12-31",
      cell: (r) => <ValidUntilCell value={r.entry.valid_until} now={now} />,
    },
    {
      key: "actions",
      header: "Actions",
      width: "15rem",
      cell: (r) => {
        const status = r.entry.status ?? "approved";
        const busy = busyId === r.entry.id;
        return (
          <div className="flex flex-wrap gap-1" role="group" aria-label={`Actions for ${r.entry.id}`}>
            <Button size="sm" onClick={() => onEdit(r)} aria-label={`Edit ${r.entry.id}`}>
              <Pencil size={12} aria-hidden /> Edit
            </Button>
            {isAdmin && status !== "approved" ? (
              <Button
                size="sm"
                variant="primary"
                disabled={busy}
                onClick={() => onSetStatus(r, "approved")}
                aria-label={`Approve ${r.entry.id}`}
              >
                Approve
              </Button>
            ) : null}
            {isAdmin && status === "archived" ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => onSetStatus(r, "draft")}
                aria-label={`Restore ${r.entry.id} to draft`}
              >
                Restore to draft
              </Button>
            ) : null}
            {isAdmin && status !== "archived" ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => onSetStatus(r, "archived")}
                aria-label={`Archive ${r.entry.id}`}
              >
                Archive
              </Button>
            ) : null}
          </div>
        );
      },
    },
  ];

  return (
    <DataTable
      caption="Knowledge base entries"
      columns={columns}
      rows={rows}
      rowKey={(r) => r.entry.id}
      isLoading={isLoading}
      error={error}
      onRetry={onRetry}
      emptyTitle={emptyTitle ?? "No KB entries"}
      emptyHint={emptyHint ?? "Create an entry or import a JSONL file."}
      initialSort={{ key: "id", dir: "asc" }}
    />
  );
}

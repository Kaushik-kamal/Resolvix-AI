import clsx from "clsx";
import { humanize } from "../lib/format";
import { TONE_CLASSES, toneForStatus, type Tone } from "./tones";

export interface StatusChipProps {
  /** Ticket status, call outcome, KB status, gap status or SMS status ("in_progress", "approved", "needs_document"...). */
  status: string | null | undefined;
  /** Override the shown text (default: humanized status). */
  label?: string;
  /** Override the colour tone (default: derived from the status word). */
  tone?: Tone;
  className?: string;
}

export function StatusChip({ status, label, tone, className }: StatusChipProps) {
  if (!status) return <span className="text-ink-faint">{"—"}</span>;
  return (
    <span
      className={clsx(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE_CLASSES[tone ?? toneForStatus(status)],
        className,
      )}
      data-status={status}
    >
      {label ?? humanize(status)}
    </span>
  );
}

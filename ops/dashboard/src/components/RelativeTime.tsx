import { useNow } from "../hooks/useNow";
import { formatDateTime, formatRelative, parseApiDate } from "../lib/format";

export interface RelativeTimeProps {
  /** API timestamp (ISO with offset). */
  value: string | null | undefined;
  /** Re-render interval in ms (default 30000; 1000 for second-level counters). */
  tickMs?: number;
  className?: string;
}

/** "5m ago" that keeps itself fresh; hover shows the absolute time in IST. */
export function RelativeTime({ value, tickMs = 30_000, className }: RelativeTimeProps) {
  const now = useNow(tickMs);
  const date = parseApiDate(value);
  if (!date) return <span className={className}>{"—"}</span>;
  return (
    <time dateTime={date.toISOString()} title={formatDateTime(date)} className={className}>
      {formatRelative(date, now)}
    </time>
  );
}

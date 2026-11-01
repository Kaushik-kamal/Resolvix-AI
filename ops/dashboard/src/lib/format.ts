/** Formatting helpers. All dates are shown in Asia/Kolkata (IST), whatever the browser timezone is. */

export const DISPLAY_TIMEZONE = "Asia/Kolkata";
const MASK_DOTS = "•••••"; // five bullets, same as the API

/** Parse an API timestamp. A value without an offset is treated as UTC. Returns null when unparsable. */
export function parseApiDate(value: string | Date | number | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "number") return new Date(value);
  const hasZone = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(value);
  const date = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatter(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("en-GB", { timeZone: DISPLAY_TIMEZONE, hourCycle: "h23", ...options });
}

const dateTimeFmt = formatter({ day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const dateTimeSecFmt = formatter({
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});
const timeFmt = formatter({ hour: "2-digit", minute: "2-digit" });
const timeSecFmt = formatter({ hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dateFmt = formatter({ day: "2-digit", month: "short", year: "numeric" });
const partsFmt = formatter({ year: "numeric", month: "2-digit", day: "2-digit" });

/** "31 Oct 2026, 15:45 IST" */
export function formatDateTime(value: string | Date | null | undefined): string {
  const date = parseApiDate(value);
  return date ? `${dateTimeFmt.format(date)} IST` : "—";
}
/** "31 Oct, 15:45:07 IST" (with seconds, no year; for event timelines) */
export function formatDateTimeSeconds(value: string | Date | null | undefined): string {
  const date = parseApiDate(value);
  return date ? `${dateTimeSecFmt.format(date)} IST` : "—";
}
/** "15:45" or "15:45:07" with seconds=true (IST, no suffix) */
export function formatTime(value: string | Date | null | undefined, seconds = false): string {
  const date = parseApiDate(value);
  if (!date) return "—";
  return (seconds ? timeSecFmt : timeFmt).format(date);
}
/** "31 Oct 2026" */
export function formatDate(value: string | Date | null | undefined): string {
  const date = parseApiDate(value);
  return date ? dateFmt.format(date) : "—";
}

/** Calendar date (YYYY-MM-DD) of an instant in IST. */
export function istDateKey(value: Date): string {
  const parts = partsFmt.formatToParts(value);
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")}`;
}

/** UTC ISO string of 00:00 IST on the day containing `now`. Use it for `GET /v1/calls?from=` ("today"). */
export function startOfTodayIST(now: Date = new Date()): string {
  const key = istDateKey(now);
  return new Date(`${key}T00:00:00+05:30`).toISOString();
}

/** "42s", "3m 05s", "1h 02m" from a number of seconds. Negative or invalid values show "0s". */
export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds === null || totalSeconds === undefined || !Number.isFinite(totalSeconds)) return "—";
  const secs = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

/** Whole seconds between two instants (never negative). `end` defaults to now. */
export function secondsBetween(start: string | Date | null | undefined, end?: string | Date | number | null): number {
  const s = parseApiDate(start);
  if (!s) return 0;
  const e = end === undefined || end === null ? new Date() : parseApiDate(end);
  if (!e) return 0;
  return Math.max(0, Math.floor((e.getTime() - s.getTime()) / 1000));
}

/** Age of a timestamp as a short phrase: "just now", "5m ago", "2h ago", "3d ago". */
export function formatRelative(value: string | Date | null | undefined, now: Date | number = new Date()): string {
  const date = parseApiDate(value);
  if (!date) return "—";
  const nowMs = typeof now === "number" ? now : now.getTime();
  const diff = Math.floor((nowMs - date.getTime()) / 1000);
  if (diff < 0) return "just now"; // small clock skew between API and browser
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ---------------------------------------------------------------- phone numbers
/** True when the value already contains the mask bullets (what the API sends unless ?reveal=true). */
export function isMasked(value: string | null | undefined): boolean {
  return !!value && value.includes("•");
}

/**
 * Same rule as the API: first 3 chars + five bullets + last 4; "•••" when shorter than 8 characters;
 * null stays null. Already-masked input is returned unchanged.
 */
export function maskNumber(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (isMasked(value)) return value;
  if (value.length < 8) return "•••";
  return value.slice(0, 3) + MASK_DOTS + value.slice(-4);
}

/**
 * What the UI shows for a phone number: "—" when missing; the masked form by default (an unmasked number is
 * re-masked here as a second line of defence); the full number only when `revealed` is true.
 */
export function displayNumber(value: string | null | undefined, revealed = false): string {
  if (value === null || value === undefined || value === "") return "—";
  if (revealed || isMasked(value)) return value;
  return maskNumber(value) ?? "—";
}

// ---------------------------------------------------------------- misc
/** "exam_cell" -> "Exam cell" */
export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  const text = value.replace(/[_-]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** 1234 -> "1,234" (en-IN grouping is not used: counts here are small). */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US").format(value);
}

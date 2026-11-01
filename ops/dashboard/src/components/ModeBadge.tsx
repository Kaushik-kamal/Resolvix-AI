import clsx from "clsx";
import { TONE_CLASSES } from "./tones";

export interface ModeBadgeProps {
  /** SmsResult.mode / healthz notify_mode: "mock" or "live". Anything else is shown as is. */
  mode: "mock" | "live" | string | null | undefined;
  /** Text before the bracket, default "SMS" -> "SMS (mock)". */
  prefix?: string;
  className?: string;
}

/**
 * "SMS (mock)" in amber for recorded-only messages, "SMS (live)" in green for messages sent through the provider.
 * Mock messages are never presented as real deliveries (PRD section 5).
 */
export function ModeBadge({ mode, prefix = "SMS", className }: ModeBadgeProps) {
  if (!mode) return null;
  const live = mode === "live";
  return (
    <span
      className={clsx(
        "inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-semibold",
        live ? TONE_CLASSES.good : TONE_CLASSES.warn,
        className,
      )}
      data-mode={mode}
      title={live ? "Sent through the live SMS provider" : "Mock mode: recorded only, nothing was sent"}
    >
      {prefix} ({mode})
    </span>
  );
}

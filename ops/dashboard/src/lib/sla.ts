import type { Priority } from "../api/extra";

/**
 * SLA-ish response targets per priority, in minutes since the ticket was created. Display only: the dashboard never
 * escalates or changes anything because a target was missed. Tune here (single place).
 */
export const SLA_TARGET_MINUTES: Record<Priority, number> = {
  P1: 15,
  P2: 4 * 60,
  P3: 24 * 60,
  P4: 72 * 60,
};

/** Share of the target after which a ticket is shown as "at risk". */
export const SLA_WARN_RATIO = 0.75;

export type SlaState = "ok" | "warn" | "breached";

export interface SlaInfo {
  state: SlaState;
  targetMinutes: number;
  elapsedSeconds: number;
  /** seconds left until the target; negative once breached */
  remainingSeconds: number;
}

/** Elapsed time against the target of `priority`. `elapsedSeconds` is the ticket age (now - created_at). */
export function slaFor(priority: Priority, elapsedSeconds: number): SlaInfo {
  const targetMinutes = SLA_TARGET_MINUTES[priority] ?? SLA_TARGET_MINUTES.P4;
  const targetSeconds = targetMinutes * 60;
  const elapsed = Math.max(0, elapsedSeconds);
  const state: SlaState = elapsed >= targetSeconds ? "breached" : elapsed >= targetSeconds * SLA_WARN_RATIO ? "warn" : "ok";
  return { state, targetMinutes, elapsedSeconds: elapsed, remainingSeconds: targetSeconds - elapsed };
}

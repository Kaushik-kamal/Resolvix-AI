/** Pure helpers for the calls page. */
import type { CallOutcome, CallSummary } from "../../api/extra";
import { humanize } from "../../lib/format";

export const CALL_OUTCOMES: readonly CallOutcome[] = ["answered", "escalated", "transferred", "emergency", "abandoned", "failed"];

/** Query parameters of GET /v1/calls for the current filters (`active` is only sent when switched on). */
export function buildCallListParams(outcome: string, activeOnly: boolean, limit = 200) {
  return {
    ...(outcome ? { outcome } : {}),
    ...(activeOnly ? { active: true } : {}),
    limit,
  };
}

/** A call without an end time is still running. */
export function isActiveCall(call: Pick<CallSummary, "ended_at">): boolean {
  return !call.ended_at;
}

/** "answered" -> "Answered"; calls that have not ended show "In progress". */
export function outcomeLabel(call: Pick<CallSummary, "ended_at" | "outcome">): string {
  if (call.outcome) return humanize(call.outcome);
  return isActiveCall(call) ? "In progress" : "—";
}

/** "path / tier" for the last turn column; "—" when the call has no turns yet. */
export function lastTurnText(last: CallSummary["last_turn"]): string {
  if (!last) return "—";
  const path = last.path ? humanize(last.path) : "—";
  return last.tier ? `${path} / ${humanize(last.tier)}` : path;
}

/** latency_ms dict -> "llm 420 · kb 12" (milliseconds, rounded, keys in their given order). */
export function formatLatency(latency: Record<string, number> | null | undefined): string {
  const entries = Object.entries(latency ?? {}).filter(([, value]) => typeof value === "number" && Number.isFinite(value));
  if (entries.length === 0) return "—";
  return entries.map(([key, value]) => `${key} ${Math.round(value)}`).join(" · ");
}

/** "Yes" / "No" / "—" for the nullable ai_resolved flag. */
export function yesNo(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value ? "Yes" : "No";
}

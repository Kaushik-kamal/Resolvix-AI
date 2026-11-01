/**
 * Display-only helpers for the rules page. The urgency rules come from urgency_rules.yaml (Member B owns the schema
 * and may extend it), so everything here tolerates unknown keys, missing fields and unexpected value types.
 * Nothing here evaluates a rule.
 */
import type { OfficeHours } from "../../api/types";

const KNOWN_RULE_KEYS = new Set(["id", "when", "priority", "ticket_type", "department", "action", "reason"]);

const OPERATOR_SUFFIXES: [string, string][] = [
  ["_lte", "≤"],
  ["_gte", "≥"],
  ["_lt", "<"],
  ["_gt", ">"],
  ["_not_in", "not in"],
  ["_in", "in"],
];

/** Compact text for any JSON value: arrays "a, b", null "none", objects as JSON. */
export function describeValue(value: unknown): string {
  if (value === null || value === undefined) return "none";
  if (Array.isArray(value)) return value.map((v) => describeValue(v)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export interface Condition {
  /** field name without the operator suffix */
  field: string;
  /** "=", "≤", "in", ... */
  op: string;
  value: string;
}

/** `{minutes_to_event_lte: 60, blocked: true}` -> [{minutes_to_event, ≤, 60}, {blocked, =, true}]. */
export function conditionsOf(when: unknown): Condition[] {
  if (!when || typeof when !== "object" || Array.isArray(when)) {
    return when === undefined || when === null ? [] : [{ field: "when", op: "=", value: describeValue(when) }];
  }
  return Object.entries(when as Record<string, unknown>).map(([key, value]) => {
    for (const [suffix, op] of OPERATOR_SUFFIXES) {
      if (key.length > suffix.length && key.endsWith(suffix)) {
        return { field: key.slice(0, -suffix.length), op, value: describeValue(value) };
      }
    }
    return { field: key, op: "=", value: describeValue(value) };
  });
}

export interface RuleView {
  /** 1-based position: rules are evaluated top to bottom, first match wins */
  position: number;
  id: string;
  /** "P1".."P4" when valid, otherwise null (rendered as an unknown badge) */
  priority: "P1" | "P2" | "P3" | "P4" | null;
  /** raw priority text when it is not P1-P4 */
  rawPriority: string | null;
  conditions: Condition[];
  ticketType: string | null;
  department: string | null;
  action: string | null;
  reason: string | null;
  /** every key the table has no column for, as [key, text] */
  extras: [string, string][];
}

function text(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  return describeValue(value);
}

export function ruleView(raw: unknown, index: number): RuleView {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {
      position: index + 1,
      id: `(rule ${index + 1})`,
      priority: null,
      rawPriority: null,
      conditions: [],
      ticketType: null,
      department: null,
      action: null,
      reason: null,
      extras: [["value", describeValue(raw)]],
    };
  }
  const r = raw as Record<string, unknown>;
  const priorityText = text(r.priority);
  const priority = priorityText && /^P[1-4]$/.test(priorityText) ? (priorityText as RuleView["priority"]) : null;
  return {
    position: index + 1,
    id: text(r.id) ?? `(rule ${index + 1})`,
    priority,
    rawPriority: priority ? null : priorityText,
    conditions: conditionsOf(r.when),
    ticketType: text(r.ticket_type),
    department: text(r.department),
    action: text(r.action),
    reason: text(r.reason),
    extras: Object.entries(r)
      .filter(([k]) => !KNOWN_RULE_KEYS.has(k))
      .map(([k, v]) => [k, describeValue(v)] as [string, string]),
  };
}

export interface RulesDocView {
  version: string | null;
  rules: RuleView[];
  /** true when `rules` was missing or not a list */
  malformed: boolean;
  /** top-level keys other than version and rules (lexicons, ...), raw values */
  extras: [string, unknown][];
}

export function rulesDocView(doc: unknown): RulesDocView {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    return { version: null, rules: [], malformed: true, extras: [] };
  }
  const d = doc as Record<string, unknown>;
  const list = Array.isArray(d.rules) ? d.rules : null;
  return {
    version: text(d.version),
    rules: (list ?? []).map(ruleView),
    malformed: list === null,
    extras: Object.entries(d).filter(([k]) => k !== "version" && k !== "rules"),
  };
}

// ---------------------------------------------------------------- departments
const DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const DAY_NAMES: Record<string, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

/** ["mon","tue","wed","thu","fri","sat"] -> "Mon–Sat"; ["mon","wed"] -> "Mon, Wed"; unknown day names are kept as is. */
export function formatDays(days: readonly string[] | undefined | null): string {
  if (!days || days.length === 0) return "";
  const known = DAY_ORDER.filter((d) => days.includes(d));
  const unknown = days.filter((d) => !(DAY_ORDER as readonly string[]).includes(d));
  const parts: string[] = [];
  let i = 0;
  while (i < known.length) {
    let j = i;
    while (j + 1 < known.length && DAY_ORDER.indexOf(known[j + 1]!) === DAY_ORDER.indexOf(known[j]!) + 1) j++;
    const first = DAY_NAMES[known[i]!]!;
    const last = DAY_NAMES[known[j]!]!;
    parts.push(j - i >= 2 ? `${first}–${last}` : j - i === 1 ? `${first}, ${last}` : first);
    i = j + 1;
  }
  return [...parts, ...unknown].join(", ");
}

/** One line per OfficeHours block: "Mon–Fri 09:00–17:00". */
export function formatHours(hours: readonly OfficeHours[] | undefined | null): string[] {
  return (hours ?? []).map((h) => `${formatDays(h.days)} ${h.open}–${h.close}`.trim());
}

/** Public emergency numbers (112, 100) are not private; anything longer is treated like a phone number and masked. */
export function isShortPublicNumber(value: string): boolean {
  return /^\d{2,5}$/.test(value.trim());
}

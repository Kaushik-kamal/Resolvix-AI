/** Pure helpers for the tickets page (no React): filtering, search, priority_reason / note / event parsing. */
import type { TicketEventRow, TicketRow, TicketStatus } from "../../api/extra";
import { maskNumber } from "../../lib/format";
import { prioritySort } from "../../lib/prioritySort";

export const TICKET_STATUSES: readonly TicketStatus[] = ["open", "in_progress", "resolved", "closed"];
export const TICKET_PRIORITIES = ["P1", "P2", "P3", "P4"] as const;

export interface TicketFilters {
  status: string;
  department: string;
  priority: string;
  /** free text; matches summary, ticket id and department */
  query: string;
}

export const EMPTY_FILTERS: TicketFilters = { status: "", department: "", priority: "", query: "" };

/** Client-side search over summary, ticket id and department (the caller number is masked, so it is not searched). */
export function matchesSearch(ticket: TicketRow, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [ticket.summary, ticket.ticket_id, ticket.department, ticket.department.replace(/_/g, " ")];
  return needle
    .split(/\s+/)
    .every((word) => haystack.some((field) => (field ?? "").toLowerCase().includes(word)));
}

/**
 * Applies every filter on the client (the server already filtered status/department/priority when the query was made;
 * repeating it keeps cached lists and SSE-refreshed lists consistent) and orders P1 -> P4, newest first.
 */
export function filterTickets(tickets: readonly TicketRow[], filters: TicketFilters): TicketRow[] {
  const matching = tickets.filter(
    (t) =>
      (!filters.status || t.status === filters.status) &&
      (!filters.department || t.department === filters.department) &&
      (!filters.priority || t.priority === filters.priority) &&
      matchesSearch(t, filters.query),
  );
  return prioritySort(matching);
}

export interface ParsedReason {
  /** rule id such as "R-EXAM-60", or null when the reason has no rule prefix */
  ruleId: string | null;
  /** the text after the rule id ("exam in 15 min") */
  text: string;
}

const RULE_ID = /^R-[A-Z0-9-]+/;

/** "R-EXAM-60: exam in 15 min" -> {ruleId: "R-EXAM-60", text: "exam in 15 min"}. */
export function parsePriorityReason(reason: string | null | undefined): ParsedReason {
  const value = (reason ?? "").trim();
  const match = RULE_ID.exec(value);
  if (!match) return { ruleId: null, text: value };
  const rest = value.slice(match[0].length).replace(/^\s*[:\-–—]\s*/, "").trim();
  return { ruleId: match[0], text: rest };
}

export interface ParsedNote {
  at: string | null;
  actor: string | null;
  text: string;
}

const NOTE = /^\[([^\]]+)\]\s+([^:]+?):\s*([\s\S]*)$/;

/** Notes are stored as "[<iso>] <actor>: <text>". Anything else is shown as plain text. */
export function parseNote(note: string): ParsedNote {
  const match = NOTE.exec(note);
  if (!match) return { at: null, actor: null, text: note };
  return { at: match[1] ?? null, actor: match[2] ?? null, text: match[3] ?? "" };
}

/** Events oldest first (newest last); stable for equal timestamps. */
export function sortEvents(events: readonly TicketEventRow[]): TicketEventRow[] {
  return events
    .map((event, index) => ({ event, index, time: Date.parse(event.at) }))
    .sort((a, b) => (Number.isNaN(a.time) || Number.isNaN(b.time) ? a.index - b.index : a.time - b.time || a.index - b.index))
    .map((entry) => entry.event);
}

const LONG_DIGITS = /^\+?[\d\s-]{8,}$/;

/** Payload values that look like phone numbers are masked before they reach the screen. */
export function safePayloadValue(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return LONG_DIGITS.test(text) ? (maskNumber(text.replace(/[\s-]/g, "")) ?? text) : text;
}

/** Key/value pairs of an event payload without the keys that the timeline renders itself. */
export function payloadEntries(payload: Record<string, unknown> | undefined, skip: readonly string[] = []): [string, string][] {
  return Object.entries(payload ?? {})
    .filter(([key, value]) => !skip.includes(key) && value !== null && value !== undefined && value !== "")
    .map(([key, value]) => [key, safePayloadValue(value)] as [string, string]);
}

/** Body for PATCH /v1/tickets/{id}: only fields the user actually changed. */
export interface StatusChange {
  currentStatus: string;
  nextStatus: string;
  resolution: string;
}
export function buildStatusPatch({ currentStatus, nextStatus, resolution }: StatusChange) {
  const patch: { status?: TicketStatus; resolution?: string } = {};
  if (nextStatus !== currentStatus) patch.status = nextStatus as TicketStatus;
  const text = resolution.trim();
  if (text && (nextStatus === "resolved" || nextStatus === "closed")) patch.resolution = text;
  return patch;
}

/** The API sends one status SMS only for a real status change on a ticket that has a call and a callback number. */
export function mayTriggerSms(ticket: Pick<TicketRow, "call_id" | "callback_number">): boolean {
  return Boolean(ticket.call_id && ticket.callback_number);
}

// ---------------------------------------------------------------- "Create KB draft from resolution" (L9)
const RESOLUTION_PREFIX = /^\s*Resolution:\s*/i;

/**
 * The newest resolution text of a ticket. PATCH {resolution} is stored as the note "[<iso>] <actor>: Resolution: <text>"
 * (the contract has no Ticket.resolution field), so look for the newest note whose text starts with "Resolution:" and
 * return what follows, without the timestamp/actor prefix. Null when there is none.
 */
export function extractResolution(notes: readonly string[] | null | undefined): string | null {
  const list = notes ?? [];
  for (let i = list.length - 1; i >= 0; i--) {
    const { text } = parseNote(list[i] ?? "");
    if (RESOLUTION_PREFIX.test(text)) {
      const body = text.replace(RESOLUTION_PREFIX, "").trim();
      if (body) return body;
    }
  }
  return null;
}

/** The "Create KB draft from resolution" button shows for a resolved/closed ticket or one with a resolution note. */
export function canDraftFromResolution(ticket: Pick<TicketRow, "status" | "notes">): boolean {
  return ticket.status === "resolved" || ticket.status === "closed" || extractResolution(ticket.notes) !== null;
}

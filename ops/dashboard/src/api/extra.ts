/**
 * Hand-written types for API shapes that are not in contracts/jsonschema (list wrappers, call summary, login,
 * KB publish history, SSE payloads, ...). Generated contract types live in ./types.ts (never edit that file).
 */
import type {
  CallChannel,
  CallOutcome,
  GapCluster,
  KBEntry,
  KBVersionInfo,
  Lang,
  Path,
  Priority,
  Ticket,
  TicketEvent,
  TicketStatus,
  TicketType,
  Tier,
  TurnSummary,
} from "./types";

export type { CallOutcome, Lang, Path, Priority, Tier, TicketStatus, TicketType };

/** `{items: T[]}` wrapper used by every list endpoint. */
export interface ListResponse<T> {
  items: T[];
}

/** Ticket as returned by the API: every field is always present (the contract marks defaulted fields optional). */
export type TicketRow = Required<Ticket>;
/** Ticket event as returned by GET /v1/tickets/{id}/events (actor and payload always present). */
export type TicketEventRow = Required<TicketEvent>;
export type TicketEventKind = TicketEvent["kind"];

/** GET /v1/calls item (no schema in the contract; CallStart + CallEnd fields, numbers masked unless ?reveal=true). */
export interface CallSummary {
  call_id: string;
  channel: CallChannel;
  caller_number: string | null;
  started_at: string;
  ended_at: string | null;
  kb_version: string;
  lang: Lang;
  outcome: CallOutcome | null;
  ai_resolved: boolean | null;
  turns_count: number;
  /** additive on the list endpoint only: the latest stored turn (null before the first turn) */
  last_turn?: { turn_index: number; path: string; tier: string | null; lang: string } | null;
}

/** GET /v1/calls/{id}. Writes a transcript_viewed audit row on every call. */
export interface CallDetail {
  call: CallSummary;
  turns: TurnSummary[];
}

export interface LoginResponse {
  success: boolean;
  email: string;
}

/** GET /v1/auth/me */
export interface Me {
  email: string;
  /** "admin" or "staff" */
  role: string;
  department: string | null;
}

/** SMS / notification mode: mock records only, live sends through Twilio. */
export type NotifyMode = "mock" | "live";

/** GET /healthz */
export interface Health {
  status: string;
  contract_version: string;
  notify_mode: NotifyMode;
  runtime_mode?: string;
}

/** Per-entry metadata next to the strict KBEntry items of GET /v1/kb/entries. */
export interface KBEntryMeta {
  flagged: boolean;
  updated_at: string;
  updated_by: string | null;
}

/**
 * GET /v1/kb/entries. `items` are strict KBEntry objects (no extra keys); the injection-scan marker lives beside
 * them: flagged = flagged_ids.includes(item.id) or meta[item.id].flagged. Flagged entries cannot be approved.
 */
export interface KBEntriesResponse {
  items: KBEntry[];
  flagged_ids: string[];
  meta: Record<string, KBEntryMeta>;
}

/** Response of POST /v1/kb/entries (201) and POST /v1/kb/entries/{id}/status (200). */
export interface KBSaveResult {
  id: string;
  status: "draft" | "approved" | "archived";
  flagged: boolean;
  entry: KBEntry;
}

/** Response of POST /v1/gaps (201). */
export interface GapCreated {
  status: string;
  gap_id: number;
  cluster_id: string;
  count: number;
}

/** POST /v1/kb/import */
export interface KBImportResult {
  imported: number;
  flagged: number;
  errors: { line: number; message: string }[];
}

/**
 * GET /v1/kb/publishes (additive, newest first): one row per publish. `info` is the KBVersionInfo (in mock mode its
 * warnings contain "mock publish: ..."), `mode` is "mock" | "live".
 */
export interface KBPublishRecord {
  id?: number;
  kb_version: string;
  info?: KBVersionInfo | null;
  mode?: NotifyMode | string;
  actor?: string;
  at: string;
  [extra: string]: unknown;
}

export type GapStatus = GapCluster["status"];

/** One rule from GET /v1/urgency-rules (raw urgency_rules.yaml as JSON). */
export interface UrgencyRule {
  id: string;
  when: Record<string, unknown>;
  priority: Priority;
  ticket_type?: TicketType;
  department?: string;
  action?: string;
  reason?: string;
  [extra: string]: unknown;
}
export interface UrgencyRulesDoc {
  version: number;
  rules: UrgencyRule[];
  [extra: string]: unknown;
}

/** Bodies of the small system endpoints. */
export interface OkResponse {
  status: string;
  created?: boolean;
  updated?: boolean;
}

// ---------------------------------------------------------------- SSE (see ops/docs/SSE_EVENTS.md)
interface Stamped {
  /** publish time, UTC ISO-8601 with offset */
  ts: string;
}

export interface CallStartedEvent extends Stamped {
  call_id: string;
  channel: CallChannel;
  caller_number: string | null;
  started_at: string;
  kb_version: string;
  lang: Lang;
}
export interface CallTurnEvent extends Stamped {
  call_id: string;
  turn_index: number;
  path: Path;
  tier: Tier | null;
  lang: Lang;
  priority: Priority | null;
  turns_count: number;
}
export interface CallEndedEvent extends Stamped {
  call_id: string;
  ended_at: string;
  outcome: CallOutcome;
  ai_resolved: boolean;
  turns_count: number;
}
export interface TicketCreatedEvent extends Stamped {
  ticket_id: string;
  call_id: string | null;
  type: TicketType;
  priority: Priority;
  priority_reason: string;
  department: string;
  status: TicketStatus;
  summary: string;
  caller_number: string | null;
  callback_number: string | null;
  callback_requested: boolean;
  created_at: string;
}
export interface AlertP1Event extends Stamped {
  ticket_id: string;
  call_id: string | null;
  type: TicketType;
  department: string;
  priority: Priority;
  priority_reason: string;
  summary: string;
  caller_number: string | null;
  callback_number: string | null;
  created_at: string;
}
export interface TicketUpdatedEvent extends Stamped {
  ticket_id: string;
  status: TicketStatus;
  assignee: string | null;
  priority: Priority;
  department: string;
  updated_at: string;
}
/** gap.created: emitted by POST /v1/gaps after commit (no question text, call id or number). */
export interface GapCreatedEvent extends Stamped {
  gap_id: number;
  cluster_id: string;
  label: string;
  department_guess: string | null;
  count: number;
}

export interface StreamEventMap {
  "call.started": CallStartedEvent;
  "call.turn": CallTurnEvent;
  "call.ended": CallEndedEvent;
  "ticket.created": TicketCreatedEvent;
  "ticket.updated": TicketUpdatedEvent;
  "alert.p1": AlertP1Event;
  "gap.created": GapCreatedEvent;
}
export type StreamEventName = keyof StreamEventMap;
export const STREAM_EVENT_NAMES: readonly StreamEventName[] = [
  "call.started",
  "call.turn",
  "call.ended",
  "ticket.created",
  "ticket.updated",
  "alert.p1",
  "gap.created",
];

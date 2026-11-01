/**
 * Typed client for the ops-api. Every function returns the parsed JSON body and throws ApiError on failure.
 *
 * Auth is the `resolvix_session` cookie: requests always use credentials "include". With VITE_OPS_API_URL empty the
 * browser talks to the Vite dev proxy (same origin). Numbers are masked unless `reveal: true` is passed (audited).
 */
import type {
  CallEnd,
  CallStart,
  DepartmentsConfig,
  ErrorBody,
  GapCluster,
  GapCreate,
  KBEntry,
  KBExport,
  KBVersionInfo,
  SmsRequest,
  SmsResult,
  TicketCreate,
  TicketCreated,
  TicketEvent,
  TicketPatch,
  TurnSummary,
} from "./types";
import type {
  CallDetail,
  CallSummary,
  GapStatus,
  Health,
  KBEntriesResponse,
  KBSaveResult,
  GapCreated,
  KBImportResult,
  KBPublishRecord,
  ListResponse,
  LoginResponse,
  Me,
  OkResponse,
  TicketEventRow,
  TicketRow,
  UrgencyRulesDoc,
} from "./extra";

// ---------------------------------------------------------------- errors
export type ApiErrorCode = ErrorBody["code"] | "network_error" | "bad_response";

/** Thrown for every non-2xx response and for network failures. Mirrors the ErrorEnvelope {error:{...}}. */
export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly retryable: boolean;
  readonly details: Record<string, string>;

  constructor(init: {
    code: ApiErrorCode;
    message: string;
    status: number;
    retryable?: boolean;
    details?: Record<string, string>;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.code = init.code;
    this.status = init.status;
    this.retryable = init.retryable ?? false;
    this.details = init.details ?? {};
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

function codeFromStatus(status: number): ApiErrorCode {
  if (status === 401 || status === 403) return "unauthorized";
  if (status === 404 || status === 405) return "not_found";
  if (status === 409) return "conflict";
  if (status === 400 || status === 422) return "validation_error";
  if (status === 429) return "rate_limited";
  if (status === 502 || status === 503) return "upstream_error";
  if (status === 504) return "timeout";
  return "internal";
}

// ---------------------------------------------------------------- base URL + 401 handling
/** Base URL of the API. Empty string means same origin (Vite proxy). Trailing slashes are removed. */
export function apiBase(): string {
  const raw = (import.meta.env?.VITE_OPS_API_URL ?? "") as string;
  return raw.trim().replace(/\/+$/, "");
}

export function apiUrl(path: string): string {
  return `${apiBase()}${path}`;
}

type UnauthorizedHandler = () => void;

/** Where an expired session lands: the login page shows "Your session expired, please sign in again" for expired=1. */
export const SESSION_EXPIRED_URL = "/login?expired=1";

function defaultUnauthorized(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname.startsWith("/login")) return;
  window.location.assign(SESSION_EXPIRED_URL);
}

let unauthorizedHandler: UnauthorizedHandler = defaultUnauthorized;

/** Run the 401 handler (REST 401 and the SSE session probe both end here). */
export function handleUnauthorized(): void {
  unauthorizedHandler();
}

/** Replace the 401 handler (tests, or an app that prefers router navigation). Returns a function that restores it. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): () => void {
  const previous = unauthorizedHandler;
  unauthorizedHandler = handler ?? defaultUnauthorized;
  return () => {
    unauthorizedHandler = previous;
  };
}

// ---------------------------------------------------------------- request core
type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue>;

export function buildQuery(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export interface RequestOptions {
  query?: Query;
  /** JSON body (objects) or FormData (sent as multipart; the browser sets the boundary header). */
  body?: unknown;
  signal?: AbortSignal;
  /** Do not trigger the 401 redirect (login attempts and the auth probe handle 401 themselves). */
  noRedirect?: boolean;
}

export async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const url = apiUrl(path) + buildQuery(options.query);
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (typeof FormData !== "undefined" && options.body instanceof FormData) {
    body = options.body;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(url, { method, headers, body, credentials: "include", signal: options.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError({
      code: "network_error",
      message: err instanceof Error && err.message ? `Network error: ${err.message}` : "Network error",
      status: 0,
      retryable: true,
    });
  }

  const text = await response.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
  }

  if (!response.ok) {
    const envelope = (parsed as { error?: Partial<ErrorBody> } | undefined)?.error;
    const error = new ApiError({
      code: (envelope?.code as ApiErrorCode | undefined) ?? codeFromStatus(response.status),
      message: envelope?.message || response.statusText || `Request failed (${response.status})`,
      status: response.status,
      retryable: envelope?.retryable ?? response.status >= 500,
      details: envelope?.details ?? {},
    });
    if (response.status === 401 && !options.noRedirect) unauthorizedHandler();
    throw error;
  }

  if (!text) return undefined as T;
  if (parsed === undefined) {
    throw new ApiError({ code: "bad_response", message: "Response was not valid JSON", status: response.status });
  }
  return parsed as T;
}

const get = <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>("GET", path, { query, signal });
const post = <T>(path: string, body?: unknown, opts: RequestOptions = {}) =>
  request<T>("POST", path, { ...opts, body: body ?? {} });

// ---------------------------------------------------------------- health + auth
export const healthz = (signal?: AbortSignal) => get<Health>("/healthz", undefined, signal);

/** A wrong password is a 401: no redirect, the form shows the ApiError. */
export const login = (email: string, password: string) =>
  post<LoginResponse>("/v1/auth/login", { email, password }, { noRedirect: true });
/** 401 here is normal (not signed in): no redirect, the route guard decides. */
export const me = (signal?: AbortSignal) => request<Me>("GET", "/v1/auth/me", { signal, noRedirect: true });
export const logout = () => post<{ success: boolean }>("/v1/auth/logout", undefined, { noRedirect: true });

// ---------------------------------------------------------------- calls
export interface ListCallsParams {
  /** ISO datetime: only calls started at or after it */
  from?: string;
  outcome?: string;
  /** additive: only calls that have not ended */
  active?: boolean;
  limit?: number;
}
/** Remove `reveal` even if an untyped caller passes it: only the detail endpoints accept it (the lists answer 422). */
function withoutReveal<P extends object>(params: P): Omit<P, "reveal"> {
  const { reveal: _reveal, ...rest } = params as P & { reveal?: unknown };
  return rest as Omit<P, "reveal">;
}
/** Lists are always masked: `reveal` is not accepted here (use getCall for one call). */
export const listCalls = (params: ListCallsParams = {}, signal?: AbortSignal) =>
  get<ListResponse<CallSummary>>("/v1/calls", { ...withoutReveal(params) }, signal);
/** Audited: always logs transcript_viewed; reveal adds number_revealed. */
export const getCall = (callId: string, opts: { reveal?: boolean } = {}, signal?: AbortSignal) =>
  get<CallDetail>(`/v1/calls/${encodeURIComponent(callId)}`, { reveal: opts.reveal }, signal);
/** System endpoints (A writes these; useful for tests and dev tooling). */
export const startCall = (body: CallStart) => post<OkResponse>("/v1/calls", body);
export const appendTurn = (callId: string, body: TurnSummary) =>
  post<TurnSummary>(`/v1/calls/${encodeURIComponent(callId)}/turns`, body);
export const endCall = (callId: string, body: CallEnd) =>
  post<OkResponse>(`/v1/calls/${encodeURIComponent(callId)}/end`, body);

// ---------------------------------------------------------------- tickets
export interface ListTicketsParams {
  status?: string;
  department?: string;
  priority?: string;
  caller_number?: string;
  limit?: number;
}
/** Lists are always masked: `reveal` is not accepted here (use getTicket for one ticket). */
export const listTickets = (params: ListTicketsParams = {}, signal?: AbortSignal) =>
  get<ListResponse<TicketRow>>("/v1/tickets", { ...withoutReveal(params) }, signal);
export const getTicket = (ticketId: string, opts: { reveal?: boolean } = {}, signal?: AbortSignal) =>
  get<TicketRow>(`/v1/tickets/${encodeURIComponent(ticketId)}`, { reveal: opts.reveal }, signal);
export const createTicket = (body: TicketCreate) => post<TicketCreated>("/v1/tickets", body);
/** A real status change sends ONE status SMS (when consent exists); the response is the masked Ticket. */
export const patchTicket = (ticketId: string, body: TicketPatch) =>
  request<TicketRow>("PATCH", `/v1/tickets/${encodeURIComponent(ticketId)}`, { body });
export const listTicketEvents = (ticketId: string, signal?: AbortSignal) =>
  get<ListResponse<TicketEventRow>>(`/v1/tickets/${encodeURIComponent(ticketId)}/events`, undefined, signal);
export const addTicketEvent = (ticketId: string, body: TicketEvent) =>
  post<OkResponse>(`/v1/tickets/${encodeURIComponent(ticketId)}/events`, body);

// ---------------------------------------------------------------- notifications
export const sendSms = (body: SmsRequest) => post<SmsResult>("/v1/notifications/sms", body);

// ---------------------------------------------------------------- gaps
export const createGap = (body: GapCreate) => post<GapCreated>("/v1/gaps", body);
export const listGapClusters = (signal?: AbortSignal) =>
  get<ListResponse<GapCluster>>("/v1/gaps/clusters", undefined, signal);
export const patchGapCluster = (clusterId: string, status: GapStatus) =>
  request<GapCluster>("PATCH", `/v1/gaps/clusters/${encodeURIComponent(clusterId)}`, { body: { status } });

// ---------------------------------------------------------------- knowledge base
export interface ListKbEntriesParams {
  status?: "draft" | "approved" | "archived";
}
export const listKbEntries = (params: ListKbEntriesParams = {}, signal?: AbortSignal) =>
  get<KBEntriesResponse>("/v1/kb/entries", { ...params }, signal);
/** Create or update one entry; new and edited entries start as draft. */
export const saveKbEntry = (entry: KBEntry) => post<KBSaveResult>("/v1/kb/entries", entry);
/** Multipart upload of a kb.jsonl file (field name "file"). */
export function importKb(file: File | Blob, filename = "kb.jsonl"): Promise<KBImportResult> {
  const form = new FormData();
  form.append("file", file, filename);
  return request<KBImportResult>("POST", "/v1/kb/import", { body: form });
}
export const setKbEntryStatus = (id: string, status: "draft" | "approved" | "archived") =>
  post<KBSaveResult>(`/v1/kb/entries/${encodeURIComponent(id)}/status`, { status });
export const exportKb = (signal?: AbortSignal) => get<KBExport>("/v1/kb/export", undefined, signal);
/** Admin only. 200 -> KBVersionInfo; 502 upstream_error when the voice runtime is unreachable (ApiError). */
export const publishKb = () => post<KBVersionInfo>("/v1/kb/publish");
/** Publish history (kb_publishes), newest first. */
export const listKbPublishes = (signal?: AbortSignal) =>
  get<ListResponse<KBPublishRecord>>("/v1/kb/publishes", undefined, signal);

// ---------------------------------------------------------------- config + stream
export const getDepartments = (signal?: AbortSignal) => get<DepartmentsConfig>("/v1/departments", undefined, signal);
export const getUrgencyRules = (signal?: AbortSignal) => get<UrgencyRulesDoc>("/v1/urgency-rules", undefined, signal);
/** URL for EventSource (credentials come from the cookie, so use withCredentials: true). */
export const streamUrl = () => apiUrl("/v1/stream");

/** All endpoint functions in one object, for `import { api } from "@/api"`. */
export const api = {
  healthz,
  login,
  me,
  logout,
  listCalls,
  getCall,
  startCall,
  appendTurn,
  endCall,
  listTickets,
  getTicket,
  createTicket,
  patchTicket,
  listTicketEvents,
  addTicketEvent,
  sendSms,
  createGap,
  listGapClusters,
  patchGapCluster,
  listKbEntries,
  saveKbEntry,
  importKb,
  setKbEntryStatus,
  exportKb,
  publishKb,
  listKbPublishes,
  getDepartments,
  getUrgencyRules,
  streamUrl,
};

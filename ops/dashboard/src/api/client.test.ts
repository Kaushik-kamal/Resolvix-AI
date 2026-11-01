import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  apiUrl,
  buildQuery,
  getCall,
  getTicket,
  listCalls,
  listTickets,
  me,
  patchTicket,
  publishKb,
  setUnauthorizedHandler,
  importKb,
  streamUrl,
} from "./client";
import { errorResponse, jsonResponse, mockFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  window.history.pushState({}, "", "/");
});

describe("buildQuery", () => {
  it("skips undefined, null and empty values and encodes the rest", () => {
    expect(buildQuery({ status: "open", department: undefined, priority: null, q: "", limit: 5, active: true })).toBe(
      "?status=open&limit=5&active=true",
    );
    expect(buildQuery({})).toBe("");
    expect(buildQuery(undefined)).toBe("");
    expect(buildQuery({ caller_number: "+919876540002" })).toBe("?caller_number=%2B919876540002");
  });
});

describe("request", () => {
  it("sends credentials and the query string, and returns parsed JSON", async () => {
    const fetchMock = mockFetch({ "GET /v1/tickets": { items: [{ ticket_id: "EX-1001" }] } });
    const result = await listTickets({ status: "open", priority: "P1", limit: 50 });
    expect(result.items[0].ticket_id).toBe("EX-1001");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/tickets?status=open&priority=P1&limit=50");
    expect(init.credentials).toBe("include");
    expect(init.method).toBe("GET");
  });

  it("passes active and from to /v1/calls", async () => {
    const fetchMock = mockFetch({ "GET /v1/calls": { items: [] } });
    await listCalls({ active: true, from: "2026-10-31T00:00:00+00:00" });
    expect(fetchMock.mock.calls[0][0]).toContain("active=true");
    expect(fetchMock.mock.calls[0][0]).toContain("from=2026-10-31T00%3A00%3A00%2B00%3A00");
  });

  it("never sends reveal on the list endpoints (they answer 422), even from an untyped caller", async () => {
    const fetchMock = mockFetch({ "GET /v1/calls": { items: [] }, "GET /v1/tickets": { items: [] } });
    await listCalls({ active: true, reveal: true } as never);
    await listTickets({ status: "open", reveal: true } as never);
    expect(String(fetchMock.mock.calls[0][0])).not.toContain("reveal");
    expect(String(fetchMock.mock.calls[1][0])).not.toContain("reveal");
    expect(String(fetchMock.mock.calls[1][0])).toContain("status=open");
  });

  it("sends reveal=true only on the detail endpoints", async () => {
    const fetchMock = mockFetch({ "GET /v1/calls/c1": { call: {}, turns: [] }, "GET /v1/tickets/EX-1001": {} });
    await getCall("c1", { reveal: true });
    await getTicket("EX-1001", { reveal: true });
    expect(String(fetchMock.mock.calls[0][0])).toBe("/v1/calls/c1?reveal=true");
    expect(String(fetchMock.mock.calls[1][0])).toBe("/v1/tickets/EX-1001?reveal=true");
  });

  it("encodes path ids and omits reveal when not asked", async () => {
    const fetchMock = mockFetch({ "GET /v1/calls/call%2Fx%20y": { call: {}, turns: [] } });
    // pathname of the URL object keeps percent-encoding
    await getCall("call/x y");
    expect(String(fetchMock.mock.calls[0][0])).toBe("/v1/calls/call%2Fx%20y");
  });

  it("sends JSON bodies with a content type on PATCH", async () => {
    const fetchMock = mockFetch({ "PATCH /v1/tickets/EX-1001": { ticket_id: "EX-1001", status: "in_progress" } });
    await patchTicket("EX-1001", { status: "in_progress", note: "on it" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PATCH");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({ status: "in_progress", note: "on it" });
  });

  it("uploads the KB import as multipart without a hand-set content type", async () => {
    const fetchMock = mockFetch({ "POST /v1/kb/import": { imported: 1, flagged: 0, errors: [] } });
    const result = await importKb(new Blob(['{"id":"FEE-001"}\n']), "kb.jsonl");
    expect(result.imported).toBe(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("throws ApiError with code, message, status and details from the ErrorEnvelope", async () => {
    mockFetch({
      "POST /v1/kb/publish": () =>
        jsonResponse(
          { error: { code: "upstream_error", message: "Voice runtime unreachable", retryable: true, details: { host: "a" } } },
          502,
        ),
    });
    const error = await publishKb().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.code).toBe("upstream_error");
    expect(apiError.message).toBe("Voice runtime unreachable");
    expect(apiError.status).toBe(502);
    expect(apiError.retryable).toBe(true);
    expect(apiError.details).toEqual({ host: "a" });
  });

  it("falls back to a status-derived code when the body is not an envelope", async () => {
    mockFetch({ "GET /v1/tickets": () => new Response("<html>bad gateway</html>", { status: 503, statusText: "Service Unavailable" }) });
    const error = (await listTickets().catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("upstream_error");
    expect(error.status).toBe(503);
    expect(error.message).toBe("Service Unavailable");
  });

  it("maps a network failure to a retryable network_error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = (await listTickets().catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("network_error");
    expect(error.status).toBe(0);
    expect(error.retryable).toBe(true);
  });

  it("reports an invalid JSON success body as bad_response", async () => {
    mockFetch({ "GET /healthz": () => new Response("not json", { status: 200 }) });
    const error = (await api.healthz().catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("bad_response");
  });
});

describe("401 handling", () => {
  it("calls the unauthorized handler on a 401 from a data endpoint", async () => {
    const handler = vi.fn();
    const restore = setUnauthorizedHandler(handler);
    mockFetch({ "GET /v1/tickets": () => errorResponse(401, "unauthorized", "Authentication required") });
    const error = (await listTickets().catch((e: unknown) => e)) as ApiError;
    restore();
    expect(error.status).toBe(401);
    expect(error.code).toBe("unauthorized");
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not redirect for the auth probe or a failed login", async () => {
    const handler = vi.fn();
    const restore = setUnauthorizedHandler(handler);
    mockFetch({
      "GET /v1/auth/me": () => errorResponse(401, "unauthorized", "no session"),
      "POST /v1/auth/login": () => errorResponse(401, "unauthorized", "Invalid credentials"),
    });
    await me().catch(() => undefined);
    await api.login("a@b", "wrong").catch(() => undefined);
    restore();
    expect(handler).not.toHaveBeenCalled();
  });

  it("default handler redirects to /login but never while already on /login", async () => {
    const assign = vi.fn();
    const original = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { pathname: "/tickets", search: "", assign },
    });
    try {
      mockFetch({ "GET /v1/tickets": () => errorResponse(401, "unauthorized", "x") });
      await listTickets().catch(() => undefined);
      expect(assign).toHaveBeenCalledWith("/login?expired=1");

      assign.mockClear();
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { pathname: "/login", search: "", assign },
      });
      await listTickets().catch(() => undefined);
      expect(assign).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: original });
    }
  });
});

describe("base URL", () => {
  it("is empty by default (Vite proxy) and uses VITE_OPS_API_URL when set, without trailing slash", () => {
    vi.stubEnv("VITE_OPS_API_URL", "");
    expect(apiUrl("/v1/tickets")).toBe("/v1/tickets");
    expect(streamUrl()).toBe("/v1/stream");
    vi.stubEnv("VITE_OPS_API_URL", "http://localhost:8100/");
    expect(apiUrl("/v1/tickets")).toBe("http://localhost:8100/v1/tickets");
    expect(streamUrl()).toBe("http://localhost:8100/v1/stream");
  });
});

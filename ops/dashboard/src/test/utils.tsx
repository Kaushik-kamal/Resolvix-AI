import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { AlertProvider } from "../alerts/AlertContext";
import { EventStreamProvider } from "../stream/EventStreamContext";
import { FakeEventSourceCtor } from "./fakeEventSource";

export type FetchHandler = (url: URL, init: RequestInit) => unknown | Response | Promise<unknown | Response>;

/**
 * Replace global fetch with a router. Keys are "METHOD /path" (query string ignored). A handler returns a JSON value
 * (status 200), a Response, or throws. Unrouted requests THROW so tests can never reach a real network.
 * Returns the vi.fn so tests can inspect calls: fetchMock.mock.calls.
 */
export function mockFetch(routes: Record<string, FetchHandler | unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const key = `${method} ${url.pathname}`;
    if (!(key in routes)) throw new Error(`Unrouted request in test: ${key}`);
    const route = routes[key];
    const result = typeof route === "function" ? await (route as FetchHandler)(url, init) : route;
    if (result instanceof Response) return result;
    return new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function errorResponse(status: number, code: string, message: string): Response {
  return jsonResponse({ error: { code, message, retryable: false, details: {} } }, status);
}

export function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } });
}

export interface RenderOptions {
  route?: string;
  client?: QueryClient;
  /** also mount EventStreamProvider (with FakeEventSource) and AlertProvider */
  withStream?: boolean;
}

/** Render inside QueryClientProvider + MemoryRouter (+ stream/alert providers with the fake EventSource). */
export function renderWithProviders(ui: ReactElement, { route = "/", client, withStream = false }: RenderOptions = {}) {
  const queryClient = client ?? testQueryClient();
  const inner = withStream ? (
    <EventStreamProvider EventSourceImpl={FakeEventSourceCtor} url="/v1/stream">
      <AlertProvider>{ui}</AlertProvider>
    </EventStreamProvider>
  ) : (
    ui
  );
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{inner}</MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setUnauthorizedHandler } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import LoginPage from "../pages/login/LoginPage";
import { FakeEventSource, FakeEventSourceCtor } from "../test/fakeEventSource";
import { errorResponse, mockFetch, testQueryClient } from "../test/utils";
import { EventStreamProvider, SESSION_PROBE_AFTER_ATTEMPTS } from "./EventStreamContext";

beforeEach(() => {
  FakeEventSource.reset();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const BACKOFF = { baseMs: 10, maxMs: 20 };

function mount() {
  return render(
    <QueryClientProvider client={testQueryClient()}>
      <EventStreamProvider EventSourceImpl={FakeEventSourceCtor} url="/v1/stream" backoff={BACKOFF}>
        <span>child</span>
      </EventStreamProvider>
    </QueryClientProvider>,
  );
}

/** Fail the current connection and let the backoff timer open the next one. */
async function failAndReconnect() {
  act(() => {
    FakeEventSource.last().fail();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(50);
  });
}

describe("L11: session expiry seen from the SSE stream", () => {
  it("probes /v1/auth/me after repeated errors and, on 401, stops reconnecting and runs the expired redirect", async () => {
    const handler = vi.fn();
    const restore = setUnauthorizedHandler(handler);
    const fetchMock = mockFetch({ "GET /v1/auth/me": () => errorResponse(401, "unauthorized", "Session expired") });
    mount();
    const sources = () => FakeEventSource.instances.length;
    expect(sources()).toBe(1);

    // below the threshold: no probe yet
    expect(SESSION_PROBE_AFTER_ATTEMPTS).toBe(2);
    await failAndReconnect();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(sources()).toBe(2);

    // second consecutive error: probe, 401, redirect, no further reconnect
    act(() => {
      FakeEventSource.last().fail();
    });
    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const count = sources();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(sources()).toBe(count); // stopped
    restore();
  });

  it("keeps reconnecting when the probe says the session is fine (network or server trouble only)", async () => {
    const handler = vi.fn();
    const restore = setUnauthorizedHandler(handler);
    const fetchMock = mockFetch({ "GET /v1/auth/me": { email: "a@b", role: "staff", department: "exam_cell" } });
    mount();
    await failAndReconnect();
    await failAndReconnect();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await failAndReconnect();
    expect(handler).not.toHaveBeenCalled();
    expect(FakeEventSource.instances.length).toBeGreaterThanOrEqual(4);
    restore();
  });

  it("ignores a probe that fails with a network error", async () => {
    const handler = vi.fn();
    const restore = setUnauthorizedHandler(handler);
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    mount();
    await failAndReconnect();
    await failAndReconnect();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(handler).not.toHaveBeenCalled();
    expect(FakeEventSource.instances.length).toBeGreaterThanOrEqual(3);
    restore();
  });
});

describe("login page after expiry", () => {
  function renderLogin(route: string) {
    mockFetch({ "GET /v1/auth/me": () => errorResponse(401, "unauthorized", "no session") });
    return render(
      <QueryClientProvider client={testQueryClient()}>
        <MemoryRouter initialEntries={[route]}>
          <AuthProvider>
            <LoginPage />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("shows 'Your session expired, please sign in again' for ?expired=1", async () => {
    renderLogin("/login?expired=1");
    expect(await screen.findByTestId("session-expired")).toHaveTextContent("Your session expired, please sign in again");
  });

  it("shows nothing special without the parameter", async () => {
    renderLogin("/login");
    await screen.findByRole("button", { name: "Sign in" });
    expect(screen.queryByTestId("session-expired")).not.toBeInTheDocument();
  });
});

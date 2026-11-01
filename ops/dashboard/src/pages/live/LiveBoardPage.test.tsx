import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CallSummary, TicketRow } from "../../api/extra";
import { AlertBanner } from "../../layout/AlertBanner";
import { FakeEventSource } from "../../test/fakeEventSource";
import { errorResponse, mockFetch, renderWithProviders } from "../../test/utils";
import LiveBoardPage from "./LiveBoardPage";
import { computeCounts } from "./useLiveBoardData";

const MASKED = "+91•••••0002";
const NOW = "2026-10-31T10:15:00+00:00";

function ticket(partial: Partial<TicketRow> & Pick<TicketRow, "ticket_id" | "priority">): TicketRow {
  return {
    call_id: null,
    type: "URGENT",
    priority_reason: "R-EXAM-60: exam in 15 min",
    department: "exam_cell",
    status: "open",
    summary: `Summary of ${partial.ticket_id}`,
    collected_fields: {},
    caller_number: MASKED,
    callback_number: null,
    callback_requested: false,
    transcript_excerpt: "",
    brief: "",
    assignee: null,
    notes: [],
    created_at: NOW,
    updated_at: NOW,
    resolved_at: null,
    ...partial,
  };
}
function call(partial: Partial<CallSummary> & Pick<CallSummary, "call_id">): CallSummary {
  return {
    channel: "pstn",
    caller_number: MASKED,
    started_at: new Date(Date.now() - 65_000).toISOString(),
    ended_at: null,
    kb_version: "abc",
    lang: "hinglish",
    outcome: null,
    ai_resolved: null,
    turns_count: 0,
    ...partial,
  };
}

const p1 = ticket({ ticket_id: "EX-1001", priority: "P1", summary: "Cannot find exam room" });
const p2 = ticket({ ticket_id: "AC-1002", priority: "P2", department: "accounts", summary: "Fee deadline today" });
const p3a = ticket({ ticket_id: "HO-1003", priority: "P3", department: "hostel", created_at: "2026-10-31T09:00:00+00:00" });
const p3b = ticket({ ticket_id: "HO-1004", priority: "P3", department: "hostel", created_at: "2026-10-31T10:00:00+00:00" });
const p4 = ticket({ ticket_id: "GN-1005", priority: "P4" });

function routes(overrides: Record<string, unknown> = {}) {
  return {
    "GET /v1/calls": (url: URL) => {
      if (url.searchParams.get("active") === "true") return { items: [call({ call_id: "call-1", turns_count: 2 })] };
      return {
        items: [
          call({ call_id: "t1", ended_at: NOW, outcome: "answered", ai_resolved: true }),
          call({ call_id: "t2", ended_at: NOW, outcome: "answered", ai_resolved: true }),
          call({ call_id: "t3", ended_at: NOW, outcome: "transferred", ai_resolved: false }),
          call({ call_id: "t4", ended_at: NOW, outcome: "emergency", ai_resolved: false }),
          call({ call_id: "call-1" }),
        ],
      };
    },
    "GET /v1/tickets": (url: URL) => {
      const status = url.searchParams.get("status");
      if (status === "open") return { items: [p1, p2, p3a, p3b, p4] };
      return { items: [ticket({ ticket_id: "EX-1000", priority: "P1", status: "in_progress", assignee: "exam@demo" })] };
    },
    ...overrides,
  };
}

beforeEach(() => {
  FakeEventSource.reset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderBoard() {
  return renderWithProviders(
    <>
      <AlertBanner />
      <LiveBoardPage />
    </>,
    { withStream: true },
  );
}

describe("computeCounts", () => {
  it("counts calls today, AI-resolved, escalated outcomes and open P1", () => {
    const counts = computeCounts(
      [
        call({ call_id: "a", ai_resolved: true, outcome: "answered" }),
        call({ call_id: "b", ai_resolved: false, outcome: "escalated" }),
        call({ call_id: "c", ai_resolved: false, outcome: "transferred" }),
        call({ call_id: "d", ai_resolved: false, outcome: "emergency" }),
        call({ call_id: "e", ai_resolved: false, outcome: "abandoned" }),
        call({ call_id: "f" }),
      ],
      [p1, p2, ticket({ ticket_id: "EX-9", priority: "P1", status: "resolved" })],
    );
    expect(counts).toEqual({ callsToday: 6, answeredByAi: 1, escalated: 3, p1Open: 1 });
  });
});

describe("LiveBoardPage", () => {
  it("shows counts, active calls and tickets in priority columns, newest first", async () => {
    mockFetch(routes());
    renderBoard();

    await waitFor(() => expect(screen.getByTestId("stat-calls-today")).toHaveTextContent("5"));
    expect(screen.getByTestId("stat-answered-by-ai")).toHaveTextContent("2");
    expect(screen.getByTestId("stat-escalated")).toHaveTextContent("2");
    expect(screen.getByTestId("stat-p1-open")).toHaveTextContent("2"); // EX-1001 open + EX-1000 in progress

    const call1 = await screen.findByTestId("active-call-call-1");
    expect(within(call1).getByTestId("masked-number")).toHaveTextContent(MASKED);
    expect(within(call1).getByText("hinglish")).toBeInTheDocument();
    expect(within(call1).getByTestId("call-duration")).toHaveTextContent(/^1m \d\ds$/);

    const p1Column = await screen.findByTestId("column-P1");
    expect(within(p1Column).getByText("EX-1001")).toBeInTheDocument();
    expect(within(p1Column).getByText("EX-1000")).toBeInTheDocument();
    const p3Column = screen.getByTestId("column-P3");
    const ids = within(p3Column).getAllByText(/^HO-/).map((el) => el.textContent);
    expect(ids).toEqual(["HO-1004", "HO-1003"]); // newest first
    expect(screen.getByTestId("column-P2")).toHaveTextContent("Fee deadline today");
    expect(screen.getByText(/1 open P4 ticket not shown/)).toBeInTheDocument();
    // no unmasked number anywhere
    expect(document.body.textContent).not.toMatch(/\+91\d{10}/);
  });

  it("shows the last turn path/tier from call.turn events", async () => {
    mockFetch(routes());
    renderBoard();
    const card = await screen.findByTestId("active-call-call-1");
    expect(card).toHaveTextContent("last turn: waiting for next");
    act(() => {
      FakeEventSource.last().open();
      FakeEventSource.last().emit("call.turn", {
        call_id: "call-1",
        turn_index: 2,
        path: "escalation",
        tier: "escalate",
        lang: "hinglish",
        priority: "P1",
        turns_count: 3,
        ts: NOW,
      });
    });
    await waitFor(() => expect(screen.getByTestId("active-call-call-1")).toHaveTextContent("Escalation"));
    expect(screen.getByTestId("active-call-call-1")).toHaveTextContent("Escalate");
    expect(screen.getByTestId("active-call-call-1")).toHaveTextContent("3 turns");
  });

  it("refetches tickets when ticket.created arrives", async () => {
    let created = false;
    const fetchMock = mockFetch(
      routes({
        "GET /v1/tickets": (url: URL) => {
          if (url.searchParams.get("status") === "open") return { items: created ? [p1, p2] : [p2] };
          return { items: [] };
        },
      }),
    );
    renderBoard();
    await screen.findByText("AC-1002");
    expect(screen.queryByText("EX-1001")).not.toBeInTheDocument();
    const before = fetchMock.mock.calls.length;
    created = true;
    act(() => {
      FakeEventSource.last().open();
      FakeEventSource.last().emit("ticket.created", { ticket_id: "EX-1001", priority: "P1", ts: NOW });
    });
    await screen.findByText("EX-1001");
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before);
  });

  it("alert.p1 shows the red banner, beeps unless muted, and flashes the ticket", async () => {
    const beep = vi.fn();
    const ctx = {
      state: "running",
      currentTime: 0,
      destination: {},
      resume: vi.fn(),
      createOscillator: () => ({ type: "", frequency: { value: 0 }, connect: vi.fn(), start: vi.fn(), stop: vi.fn() }),
      createGain: () => ({
        gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
        connect: vi.fn(),
      }),
    };
    class FakeAudioContext {
      constructor() {
        beep();
        return ctx as unknown as FakeAudioContext;
      }
    }
    vi.stubGlobal("AudioContext", FakeAudioContext);
    const { resetAudioForTests } = await import("../../lib/beep");
    resetAudioForTests();

    mockFetch(routes());
    renderBoard();
    await screen.findByTestId("ticket-card-EX-1001");
    expect(screen.queryByTestId("p1-banner")).not.toBeInTheDocument();

    act(() => {
      FakeEventSource.last().open();
      FakeEventSource.last().emit("alert.p1", {
        ticket_id: "EX-1001",
        call_id: "call-1",
        type: "URGENT",
        department: "exam_cell",
        priority: "P1",
        priority_reason: "R-EXAM-60",
        summary: "Cannot find exam room",
        caller_number: MASKED,
        callback_number: null,
        created_at: NOW,
        ts: NOW,
      });
    });

    const banner = await screen.findByTestId("p1-banner");
    expect(banner).toHaveTextContent("EX-1001");
    expect(banner).toHaveTextContent("Cannot find exam room");
    expect(banner).toHaveTextContent(MASKED);
    expect(beep).toHaveBeenCalled(); // an AudioContext was created to play the alert
    expect(screen.getByTestId("ticket-card-EX-1001")).toHaveAttribute("data-flashing", "true");
    expect(screen.getByTestId("ticket-card-AC-1002")).not.toHaveAttribute("data-flashing");
  });

  it("does not beep when muted (persisted in localStorage)", async () => {
    window.localStorage.setItem("resolvix.alertsMuted", "1");
    const created = vi.fn();
    class FakeAudioContext {
      constructor() {
        created();
      }
    }
    vi.stubGlobal("AudioContext", FakeAudioContext);
    const { resetAudioForTests } = await import("../../lib/beep");
    resetAudioForTests();

    mockFetch(routes());
    renderBoard();
    await screen.findByTestId("ticket-card-EX-1001");
    act(() => {
      FakeEventSource.last().open();
      FakeEventSource.last().emit("alert.p1", { ticket_id: "EX-1001", department: "exam_cell", summary: "x", ts: NOW });
    });
    await screen.findByTestId("p1-banner");
    expect(created).not.toHaveBeenCalled();
    window.localStorage.removeItem("resolvix.alertsMuted");
  });

  it("shows empty states when nothing is open", async () => {
    mockFetch(routes({ "GET /v1/calls": { items: [] }, "GET /v1/tickets": { items: [] } }));
    renderBoard();
    expect(await screen.findByText("No active calls")).toBeInTheDocument();
    expect(await screen.findByText("No open P1 tickets")).toBeInTheDocument();
    expect(screen.getByText("No open P2 tickets")).toBeInTheDocument();
    expect(screen.getByTestId("stat-calls-today")).toHaveTextContent("0");
  });

  it("shows an error state with retry for tickets and for calls", async () => {
    mockFetch(
      routes({
        "GET /v1/calls": () => errorResponse(500, "internal", "database is locked"),
        "GET /v1/tickets": () => errorResponse(500, "internal", "tickets exploded"),
      }),
    );
    renderBoard();
    expect(await screen.findByText("Could not load tickets")).toBeInTheDocument();
    expect(screen.getByText(/tickets exploded/)).toBeInTheDocument();
    expect(await screen.findByText("Could not load active calls")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /retry/i }).length).toBeGreaterThanOrEqual(2);
  });
});

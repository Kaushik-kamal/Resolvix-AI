import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { qk } from "../../api";
import type { CallSummary, Me, TicketRow } from "../../api/extra";
import { ConnectionPill } from "../../layout/ConnectionPill";
import { PROJECTOR_CLASSES, PROJECTOR_KEY, readProjector, resetProjectorCache } from "../../lib/projector";
import { FakeEventSource } from "../../test/fakeEventSource";
import { mockFetch, renderWithProviders, testQueryClient } from "../../test/utils";
import LiveBoardPage from "./LiveBoardPage";

const MASKED = "+91•••••0002";
const NOW = "2026-10-31T10:15:00+00:00";
const ADMIN: Me = { email: "admin@demo", role: "admin", department: null };
const STAFF: Me = { email: "exam@demo", role: "staff", department: "exam_cell" };

function ticket(id: string, priority: TicketRow["priority"], summary: string): TicketRow {
  return {
    ticket_id: id,
    call_id: null,
    type: "URGENT",
    priority,
    priority_reason: "R-EXAM-60: exam",
    department: "exam_cell",
    status: "open",
    summary,
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
  };
}
const TICKETS = [ticket("EX-1001", "P1", "Cannot find exam room"), ticket("EX-1002", "P2", "Fee deadline"), ticket("EX-1003", "P3", "Hostel water")];
const ACTIVE_CALL: CallSummary = {
  call_id: "call-1",
  channel: "pstn",
  caller_number: MASKED,
  started_at: new Date(Date.now() - 30_000).toISOString(),
  ended_at: null,
  kb_version: "v1",
  lang: "hinglish",
  outcome: null,
  ai_resolved: null,
  turns_count: 1,
};

function routes(activeCalls: CallSummary[] = []) {
  return {
    "GET /v1/calls": (url: URL) =>
      url.searchParams.get("active") === "true"
        ? { items: activeCalls }
        : { items: [{ ...ACTIVE_CALL, call_id: "t1", ended_at: NOW, outcome: "answered", ai_resolved: true }] },
    "GET /v1/tickets": (url: URL) => ({ items: url.searchParams.get("status") === "open" ? TICKETS : [] }),
  };
}

function renderBoard(me: Me | null) {
  const client = testQueryClient();
  if (me) client.setQueryData(qk.me, me);
  // gcTime 0 would drop the cached user (nobody observes it before the board mounts); keep it
  client.setDefaultOptions({ queries: { retry: false, gcTime: Infinity, staleTime: 0 } });
  return { ...renderWithProviders(<LiveBoardPage />, { client, withStream: true }), client };
}

beforeEach(() => {
  FakeEventSource.reset();
  window.localStorage.clear();
  resetProjectorCache();
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  resetProjectorCache();
});

describe("M4: staff live board", () => {
  it("replaces calls-today / answered-by-AI / escalated with a note, keeps P1 open, and does not fetch today's calls", async () => {
    const fetchMock = mockFetch(routes());
    renderBoard(STAFF);
    await waitFor(() => expect(screen.getByTestId("stat-p1-open")).toHaveTextContent("1"));
    expect(screen.queryByTestId("stat-calls-today")).not.toBeInTheDocument();
    expect(screen.queryByTestId("stat-answered-by-ai")).not.toBeInTheDocument();
    expect(screen.queryByTestId("stat-escalated")).not.toBeInTheDocument();
    const note = screen.getByTestId("staff-counts-note");
    expect(note).toHaveTextContent(/shown to admins only/);
    expect(note).toHaveTextContent(/Exam cell/);
    // only the "active" calls list is requested; the all-calls-today query (from=...) is skipped
    const callRequests = fetchMock.mock.calls.map(([u]) => new URL(String(u), "http://localhost")).filter((u) => u.pathname === "/v1/calls");
    expect(callRequests.length).toBeGreaterThan(0);
    expect(callRequests.every((u) => u.searchParams.get("active") === "true")).toBe(true);
  });

  it("shows an explanatory empty state in the Active calls panel", async () => {
    mockFetch(routes([]));
    renderBoard(STAFF);
    expect(await screen.findByText("Live calls are visible to admins")).toBeInTheDocument();
    expect(screen.getByText(/once they produce a ticket for your department/)).toBeInTheDocument();
    expect(screen.queryByText("No active calls")).not.toBeInTheDocument();
  });

  it("lists scoped active calls with a note when there are some", async () => {
    mockFetch(routes([ACTIVE_CALL]));
    renderBoard(STAFF);
    expect(await screen.findByTestId("active-call-call-1")).toBeInTheDocument();
    expect(screen.getByTestId("staff-calls-note")).toHaveTextContent(/linked to a ticket of your department/);
  });

  it("leaves the admin board unchanged", async () => {
    mockFetch(routes([]));
    renderBoard(ADMIN);
    await waitFor(() => expect(screen.getByTestId("stat-calls-today")).toHaveTextContent("1"));
    expect(screen.getByTestId("stat-answered-by-ai")).toHaveTextContent("1");
    expect(screen.getByTestId("stat-escalated")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-counts-note")).not.toBeInTheDocument();
    expect(await screen.findByText("No active calls")).toBeInTheDocument();
  });
});

describe("L10: live regions", () => {
  it("the counts row and the connection pill are polite live regions", async () => {
    mockFetch(routes());
    renderWithProviders(
      <>
        <ConnectionPill />
        <LiveBoardPage />
      </>,
      { withStream: true },
    );
    expect(screen.getByRole("status", { name: /Live updates/ })).toHaveAttribute("aria-live", "polite");
    expect(await screen.findByTestId("counts-row")).toHaveAttribute("aria-live", "polite");
  });
});

describe("Projector mode", () => {
  it("is off by default, toggles larger type on cards, counts and columns, and persists in localStorage", async () => {
    const user = userEvent.setup();
    mockFetch(routes());
    renderBoard(ADMIN);
    const board = await screen.findByTestId("live-board");
    const card = await screen.findByTestId("ticket-card-EX-1001");
    const toggle = screen.getByRole("button", { name: /Projector/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(board).toHaveAttribute("data-projector", "false");
    expect(card.querySelector("p")).toHaveClass(PROJECTOR_CLASSES.cardSummaryNormal);
    expect(screen.getByTestId("stat-calls-today").children[1]).toHaveClass(PROJECTOR_CLASSES.statValueNormal);

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(board).toHaveAttribute("data-projector", "true");
    expect(card).toHaveAttribute("data-projector", "true");
    expect(card.querySelector("p")).toHaveClass(PROJECTOR_CLASSES.cardSummary);
    expect(card.querySelector("p")).not.toHaveClass(PROJECTOR_CLASSES.cardSummaryNormal);
    expect(screen.getByTestId("stat-calls-today").children[1]).toHaveClass(PROJECTOR_CLASSES.statValue);
    expect(window.localStorage.getItem(PROJECTOR_KEY)).toBe("1");
    // 1.4x: text-base is 1rem vs text-xs 0.75rem (1.33x), text-lg vs 13px (1.38x), text-5xl vs text-3xl (1.6x)
    expect(PROJECTOR_CLASSES.cardSummary).toBe("text-lg");

    await user.click(toggle);
    expect(window.localStorage.getItem(PROJECTOR_KEY)).toBe("0");
    expect(board).toHaveAttribute("data-projector", "false");
  });

  it("starts in projector mode when localStorage says so", async () => {
    window.localStorage.setItem(PROJECTOR_KEY, "1");
    resetProjectorCache();
    mockFetch(routes());
    renderBoard(ADMIN);
    expect(await screen.findByTestId("live-board")).toHaveAttribute("data-projector", "true");
  });

  it("keeps working when localStorage throws", async () => {
    const user = userEvent.setup();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    resetProjectorCache();
    expect(readProjector()).toBe(false);
    mockFetch(routes());
    renderBoard(ADMIN);
    await user.click(await screen.findByRole("button", { name: /Projector/ }));
    expect(screen.getByTestId("live-board")).toHaveAttribute("data-projector", "true");
    vi.restoreAllMocks();
  });

  it("keeps P1/P2/P3 columns shrinkable so nothing overflows horizontally at 1280 px (class-name check)", async () => {
    window.localStorage.setItem(PROJECTOR_KEY, "1");
    resetProjectorCache();
    mockFetch(routes([ACTIVE_CALL]));
    renderBoard(ADMIN);
    const grid = await screen.findByTestId("board-grid");
    // left column is capped at 280 px in projector mode and the right one may shrink to 0 (minmax(0,1fr))
    expect(grid.className).toContain("minmax(220px,280px)_minmax(0,1fr)");
    const columns = screen.getByTestId("ticket-columns");
    expect(columns.className).toContain("grid-cols-3");
    for (const p of ["P1", "P2", "P3"]) {
      const col = screen.getByTestId(`column-${p}`);
      expect(col).toHaveClass("min-w-0");
      expect(within(col).getByRole("heading").className).toContain(PROJECTOR_CLASSES.columnTitle);
    }
    const card = await screen.findByTestId("ticket-card-EX-1001");
    expect(card).toHaveClass("min-w-0");
    expect(card.querySelector("p")).toHaveClass("break-words");
    // no fixed pixel widths that could exceed 1280 px on the board itself
    const board = screen.getByTestId("live-board");
    expect(board.innerHTML).not.toMatch(/\bw-\[(?:[4-9]\d\d|\d{4,})px\]/);
  });
});

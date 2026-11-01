import { QueryClient } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { qk } from "../../api";
import type { TicketEventRow, TicketRow } from "../../api/extra";
import { FakeEventSource } from "../../test/fakeEventSource";
import { mockFetch, renderWithProviders } from "../../test/utils";
import { KB_DRAFT_STATE_KEY, readDraftSeed } from "../kb/draftSeed";
import { LocationProbe } from "../kb/testUtils";
import TicketsPage from "./index";
import { extractResolution, canDraftFromResolution } from "./ticketLogic";
import { titleFor, toneFor, TicketTimeline } from "./TicketTimeline";

const MASKED = "+91•••••0002";
const FULL = "+919876500002";
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

const RESOLVED = ticket({
  ticket_id: "EX-1001",
  priority: "P2",
  status: "resolved",
  summary: "Hall ticket not visible on the portal",
  notes: [
    "[2026-10-31T09:00:00+00:00] exam@demo: Called the student",
    "[2026-10-31T10:20:00+00:00] exam@demo: Resolution: Hall tickets are released 3 days before the exam; check the Exams tab.",
  ],
});
const OPEN_NO_RESOLUTION = ticket({ ticket_id: "EX-1002", priority: "P3", notes: ["[2026-10-31T09:00:00+00:00] exam@demo: Called the student"] });
const OPEN_WITH_RESOLUTION_NOTE = ticket({
  ticket_id: "EX-1003",
  priority: "P3",
  notes: ["[2026-10-31T09:00:00+00:00] exam@demo: Resolution: Use the helpdesk form."],
});

function tx(kind: TicketEventRow["kind"], payload: Record<string, string>, at = NOW): TicketEventRow {
  return { kind, actor: "system", at, payload };
}

describe("L7: SMS timeline titles and tone", () => {
  it("mock = neutral 'SMS recorded (mock)', live = green 'SMS sent', no mode = neutral 'mode unknown'", () => {
    const mock = tx("sms_sent", { mode: "mock", status: "sent" });
    const live = tx("sms_sent", { mode: "live", status: "sent" });
    const unknown = tx("sms_sent", { status: "sent" });
    expect(titleFor(mock)).toBe("SMS recorded (mock)");
    expect(titleFor(live)).toBe("SMS sent");
    expect(titleFor(unknown)).toBe("SMS recorded (mode unknown)");
    expect(toneFor(mock)).toBe("text-ink-soft border-line");
    expect(toneFor(unknown)).toBe("text-ink-soft border-line");
    expect(toneFor(live)).toContain("#3F6B49");
    // failed / suppressed unchanged
    expect(titleFor(tx("sms_failed", { mode: "live" }))).toBe("SMS failed");
    expect(toneFor(tx("sms_failed", {}))).toContain("text-p1");
    expect(titleFor(tx("sms_suppressed", { mode: "mock" }))).toBe("SMS suppressed");
    expect(toneFor(tx("sms_suppressed", {}))).toBe("text-ink-soft border-line");
    expect(toneFor(tx("transfer_connected", {}))).toContain("#3F6B49");
  });

  it("renders the titles in the timeline", () => {
    renderWithProviders(
      <TicketTimeline
        events={[
          tx("sms_sent", { mode: "mock", status: "sent", template_id: "a" }, "2026-10-31T10:00:00+00:00"),
          tx("sms_sent", { mode: "live", status: "sent", template_id: "b" }, "2026-10-31T10:01:00+00:00"),
          tx("sms_sent", { status: "sent", template_id: "c" }, "2026-10-31T10:02:00+00:00"),
        ]}
      />,
    );
    expect(screen.getByText("SMS recorded (mock)")).toBeInTheDocument();
    expect(screen.getByText("SMS sent")).toBeInTheDocument();
    expect(screen.getByText("SMS recorded (mode unknown)")).toBeInTheDocument();
    expect(screen.getByText("SMS (live)")).toBeInTheDocument();
    expect(screen.getByText("SMS (mock)")).toBeInTheDocument();
  });
});

describe("L9: resolution extraction", () => {
  it("extracts the newest 'Resolution:' note without timestamp or actor", () => {
    expect(extractResolution(RESOLVED.notes)).toBe("Hall tickets are released 3 days before the exam; check the Exams tab.");
    expect(extractResolution(["[t] a: Resolution: old", "[t] a: Resolution: newer"])).toBe("newer");
    expect(extractResolution(["Resolution: plain note"])).toBe("plain note");
    expect(extractResolution(["[t] a: just a note"])).toBeNull();
    expect(extractResolution([])).toBeNull();
    expect(extractResolution(undefined)).toBeNull();
  });
  it("offers the draft for resolved/closed tickets or when a resolution note exists", () => {
    expect(canDraftFromResolution({ status: "resolved", notes: [] })).toBe(true);
    expect(canDraftFromResolution({ status: "closed", notes: [] })).toBe(true);
    expect(canDraftFromResolution({ status: "open", notes: ["[t] a: Resolution: x"] })).toBe(true);
    expect(canDraftFromResolution({ status: "in_progress", notes: ["[t] a: hi"] })).toBe(false);
  });
});

function setup(tickets: TicketRow[]) {
  const fetchMock = mockFetch({
    "GET /v1/tickets": { items: tickets },
    "GET /v1/departments": { default_department: "exam_cell", emergency: {}, departments: [] },
    ...Object.fromEntries(
      tickets.flatMap((t) => [
        [
          `GET /v1/tickets/${t.ticket_id}`,
          (url: URL) =>
            url.searchParams.get("reveal") === "true" ? { ...t, caller_number: FULL, callback_number: "+919876500003" } : t,
        ],
        [`GET /v1/tickets/${t.ticket_id}/events`, { items: [] }],
      ]),
    ),
  });
  return fetchMock;
}

function revealCalls(fetchMock: ReturnType<typeof setup>, id: string) {
  return fetchMock.mock.calls.filter(([input]) => {
    const url = new URL(String(input), "http://localhost");
    return url.pathname === `/v1/tickets/${id}` && url.searchParams.get("reveal") === "true";
  });
}

beforeEach(() => FakeEventSource.reset());
afterEach(() => vi.unstubAllGlobals());

describe("L9: Create KB draft from resolution", () => {
  function renderApp(route: string) {
    return renderWithProviders(
      <>
        <Routes>
          <Route path="/tickets" element={<TicketsPage />} />
          <Route path="/kb" element={<LocationProbe />} />
        </Routes>
      </>,
      { route },
    );
  }

  it("navigates to /kb with a draft seed built from the ticket and its resolution note", async () => {
    setup([RESOLVED]);
    const user = userEvent.setup();
    renderApp("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await user.click(await within(dialog).findByRole("button", { name: /Create KB draft from resolution/ }));
    const probe = await screen.findByTestId("location");
    expect(probe).toHaveAttribute("data-pathname", "/kb");
    const state = JSON.parse(probe.textContent ?? "null") as Record<string, unknown>;
    expect(state[KB_DRAFT_STATE_KEY]).toEqual({
      source: "ticket",
      clusterId: "",
      ticketId: "EX-1001",
      label: "Resolved ticket EX-1001",
      department: "exam_cell",
      questionVariants: ["Hall ticket not visible on the portal"],
      idPrefix: "EC",
      answerEn: "Hall tickets are released 3 days before the exam; check the Exams tab.",
      sourceTitle: "Resolved ticket EX-1001",
    });
    // the KB page accepts exactly this shape
    expect(readDraftSeed(state)?.answerEn).toMatch(/^Hall tickets are released/);
  });

  it("is hidden for an open ticket without a resolution and shown for an open one with a resolution note", async () => {
    setup([OPEN_NO_RESOLUTION, OPEN_WITH_RESOLUTION_NOTE]);
    const first = renderApp("/tickets?ticket=EX-1002");
    const dialog = await screen.findByRole("dialog", { name: "EX-1002" });
    await within(dialog).findByText("Summary of EX-1002");
    expect(within(dialog).queryByRole("button", { name: /Create KB draft/ })).not.toBeInTheDocument();
    first.unmount();
    renderApp("/tickets?ticket=EX-1003");
    const dialog2 = await screen.findByRole("dialog", { name: "EX-1003" });
    expect(await within(dialog2).findByRole("button", { name: /Create KB draft from resolution/ })).toBeInTheDocument();
  });
});

describe("L12: reveal is a one-shot, audited fetch", () => {
  it("does not re-request reveal=true on SSE refetches, and removes the revealed data on Hide and on close", async () => {
    const user = userEvent.setup();
    const fetchMock = setup([RESOLVED]);
    // default gcTime (5 min): only an explicit removeQueries can make the revealed copy disappear
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
    renderWithProviders(<TicketsPage />, { route: "/tickets?ticket=EX-1001", withStream: true, client });
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Hall ticket not visible on the portal");
    expect(within(dialog).getAllByTestId("masked-number")[0]).toHaveTextContent(MASKED);

    await user.click(within(dialog).getByRole("button", { name: "Reveal numbers" }));
    await waitFor(() => expect(within(dialog).getAllByTestId("masked-number")[0]).toHaveTextContent(FULL));
    expect(revealCalls(fetchMock, "EX-1001")).toHaveLength(1);
    expect(client.getQueryData(qk.tickets.detail("EX-1001", true))).toBeDefined();

    // stream-driven invalidation + a reconnect: masked data refreshes, reveal is NOT asked for again
    const detailCalls = () =>
      fetchMock.mock.calls.filter(([input]) => new URL(String(input), "http://localhost").pathname === "/v1/tickets/EX-1001").length;
    const before = detailCalls();
    FakeEventSource.last().open();
    act(() => {
      FakeEventSource.last().emit("ticket.updated", { ts: NOW, ticket_id: "EX-1001", status: "resolved" });
    });
    await waitFor(() => expect(detailCalls()).toBeGreaterThan(before));
    act(() => {
      FakeEventSource.last().emit("ticket.updated", { ts: NOW, ticket_id: "EX-1001", status: "resolved" });
    });
    await act(async () => {
      await client.invalidateQueries({ queryKey: qk.tickets.all });
    });
    expect(revealCalls(fetchMock, "EX-1001")).toHaveLength(1);
    expect(within(dialog).getAllByTestId("masked-number")[0]).toHaveTextContent(FULL); // revealed copy kept

    await user.click(within(dialog).getByRole("button", { name: "Hide numbers" }));
    await waitFor(() => expect(within(dialog).getAllByTestId("masked-number")[0]).toHaveTextContent(MASKED));
    expect(client.getQueryData(qk.tickets.detail("EX-1001", true))).toBeUndefined();

    // reveal again = a second explicit audited fetch, then closing the drawer removes the copy
    await user.click(within(dialog).getByRole("button", { name: "Reveal numbers" }));
    await waitFor(() => expect(within(dialog).getAllByTestId("masked-number")[0]).toHaveTextContent(FULL));
    expect(revealCalls(fetchMock, "EX-1001")).toHaveLength(2);
    expect(client.getQueryData(qk.tickets.detail("EX-1001", true))).toBeDefined();
    await user.click(within(dialog).getByRole("button", { name: "Close panel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(client.getQueryData(qk.tickets.detail("EX-1001", true))).toBeUndefined();
    expect(client.getQueryCache().findAll({ queryKey: qk.tickets.detailAny("EX-1001") }).some((q) => JSON.stringify(q.state.data).includes(FULL))).toBe(false);
  });
});

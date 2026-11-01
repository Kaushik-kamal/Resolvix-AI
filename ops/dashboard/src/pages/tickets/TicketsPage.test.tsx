import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CallDetail, CallSummary, TicketEventRow, TicketRow } from "../../api/extra";
import { qk } from "../../api";
import { FakeEventSource } from "../../test/fakeEventSource";
import { errorResponse, mockFetch, renderWithProviders, testQueryClient } from "../../test/utils";
import TicketsPage from "./index";

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

const p1 = ticket({
  ticket_id: "EX-1001",
  priority: "P1",
  summary: "Cannot find exam room",
  call_id: "call-1",
  callback_number: "+91•••••0003",
  brief: "Student is at the gate and cannot find hall B.",
  collected_fields: { roll_no: "21CS042", exam: "Maths" },
  transcript_excerpt: "Caller: where is hall B",
});
const p2 = ticket({ ticket_id: "AC-1002", priority: "P2", department: "accounts", summary: "Fee deadline today", priority_reason: "No rule matched" });
const p3 = ticket({ ticket_id: "HO-1003", priority: "P3", department: "hostel", summary: "Water heater broken", created_at: "2026-10-31T09:00:00+00:00" });
const p3new = ticket({ ticket_id: "HO-1004", priority: "P3", department: "hostel", summary: "Mess timing question", created_at: "2026-10-31T10:00:00+00:00" });

const DEPARTMENTS = {
  default_department: "exam_cell",
  emergency: {},
  departments: [
    { key: "exam_cell", name: "Exam Cell", ticket_prefix: "EX", transfer_numbers: [], hours: [] },
    { key: "accounts", name: "Accounts", ticket_prefix: "AC", transfer_numbers: [], hours: [] },
    { key: "hostel", name: "Hostel", ticket_prefix: "HO", transfer_numbers: [], hours: [] },
  ],
};

const EVENTS: TicketEventRow[] = [
  { kind: "transfer_attempted", actor: "voice", at: "2026-10-31T10:00:00+00:00", payload: { department: "exam_cell", number: "+911234567890" } },
  { kind: "transfer_failed", actor: "voice", at: "2026-10-31T10:01:00+00:00", payload: { reason: "no_answer" } },
  {
    kind: "sms_sent",
    actor: "system",
    at: "2026-10-31T10:05:00+00:00",
    payload: { template_id: "status_change", mode: "mock", status: "sent", to: "+91•••••0003", message_id: "m1" },
  },
  {
    kind: "sms_sent",
    actor: "system",
    at: "2026-10-31T10:06:00+00:00",
    payload: { template_id: "callback_ack", mode: "live", status: "sent", to: "+91•••••0003" },
  },
  { kind: "sms_suppressed", actor: "system", at: "2026-10-31T10:07:00+00:00", payload: { template_id: "status_change", mode: "mock", reason: "no_consent" } },
  { kind: "status_changed", actor: "exam@demo", at: "2026-10-31T10:08:00+00:00", payload: { old_status: "open", new_status: "in_progress" } },
  { kind: "note_added", actor: "exam@demo", at: "2026-10-31T10:09:00+00:00", payload: { note: "Called the student" } },
];

const CALL_DETAIL: CallDetail = {
  call: {
    call_id: "call-1",
    channel: "pstn",
    caller_number: MASKED,
    started_at: NOW,
    ended_at: null,
    kb_version: "v1",
    lang: "hinglish",
    outcome: null,
    ai_resolved: null,
    turns_count: 2,
  } satisfies CallSummary,
  turns: [
    {
      call_id: "call-1",
      turn_index: 0,
      path: "faq",
      tier: "confident",
      lang: "hinglish",
      user_text_redacted: "Exam hall kahan hai?",
      assistant_text: "Hall B, second floor.",
      created_at: NOW,
    },
    {
      call_id: "call-1",
      turn_index: 1,
      path: "escalation",
      tier: null,
      lang: "hinglish",
      user_text_redacted: "Mujhe insaan se baat karni hai",
      assistant_text: "Transferring you.",
      created_at: NOW,
    },
  ],
};

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

/** Mutable server state so a PATCH followed by a refetch shows the new data. */
function setup(options: { tickets?: TicketRow[]; events?: TicketEventRow[]; patchError?: boolean } = {}) {
  const state = {
    tickets: (options.tickets ?? [p1, p2, p3, p3new]).map((t) => ({ ...t })),
    events: options.events ?? EVENTS,
  };
  const patches: unknown[] = [];
  const fetchMock = mockFetch({
    "GET /v1/tickets": (url: URL) => {
      const status = url.searchParams.get("status");
      const department = url.searchParams.get("department");
      const priority = url.searchParams.get("priority");
      return {
        items: state.tickets.filter(
          (t) => (!status || t.status === status) && (!department || t.department === department) && (!priority || t.priority === priority),
        ),
      };
    },
    "GET /v1/departments": DEPARTMENTS,
    ...Object.fromEntries(
      state.tickets.flatMap((t) => [
        [
          `GET /v1/tickets/${t.ticket_id}`,
          (url: URL) => {
            const current = state.tickets.find((x) => x.ticket_id === t.ticket_id)!;
            return url.searchParams.get("reveal") === "true"
              ? { ...current, caller_number: FULL, callback_number: current.callback_number ? "+919876500003" : null }
              : current;
          },
        ],
        [`GET /v1/tickets/${t.ticket_id}/events`, () => ({ items: state.events })],
        [
          `PATCH /v1/tickets/${t.ticket_id}`,
          (_url: URL, init: RequestInit) => {
            if (options.patchError) return errorResponse(500, "internal", "Database is busy");
            const body = JSON.parse(String(init.body)) as { status?: TicketRow["status"]; assignee?: string; note?: string; resolution?: string };
            patches.push(body);
            const current = state.tickets.find((x) => x.ticket_id === t.ticket_id)!;
            if (body.status) current.status = body.status;
            if (body.assignee !== undefined) current.assignee = body.assignee || null;
            if (body.note) current.notes = [...current.notes, `[${NOW}] exam@demo: ${body.note}`];
            return current;
          },
        ],
      ]),
    ),
    "GET /v1/calls/call-1": CALL_DETAIL,
  });
  return { state, patches, fetchMock };
}

function calls(fetchMock: ReturnType<typeof setup>["fetchMock"], method: string, pathPrefix: string) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = new URL(String(input), "http://localhost");
    return ((init as RequestInit | undefined)?.method ?? "GET") === method && url.pathname === pathPrefix;
  });
}

function renderPage(route = "/tickets", client = testQueryClient()) {
  return renderWithProviders(
    <>
      <TicketsPage />
      <LocationProbe />
    </>,
    { route, client },
  );
}

beforeEach(() => {
  FakeEventSource.reset();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("tickets list", () => {
  it("shows tickets sorted P1 to P4, newest first, with masked callers", async () => {
    setup();
    renderPage();
    await screen.findByText("EX-1001");
    const ids = screen.getAllByRole("row").slice(1).map((row) => row.getAttribute("data-row-key"));
    expect(ids).toEqual(["EX-1001", "AC-1002", "HO-1004", "HO-1003"]);
    expect(screen.getAllByText(MASKED).length).toBeGreaterThan(0);
    expect(screen.getByText("4 of 4 tickets")).toBeInTheDocument();
  });

  it("shows a loading state first", () => {
    mockFetch({ "GET /v1/tickets": () => new Promise(() => undefined), "GET /v1/departments": DEPARTMENTS });
    renderPage();
    expect(screen.getByRole("status", { name: "Loading…" })).toBeInTheDocument();
  });

  it("shows an error state with retry", async () => {
    const user = userEvent.setup();
    let fail = true;
    mockFetch({
      "GET /v1/tickets": () => (fail ? errorResponse(500, "internal", "boom") : { items: [p1] }),
      "GET /v1/departments": DEPARTMENTS,
    });
    renderPage();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("boom");
    fail = false;
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("EX-1001")).toBeInTheDocument();
  });

  it("shows an empty state and a filtered empty state with clear filters", async () => {
    const user = userEvent.setup();
    mockFetch({ "GET /v1/tickets": { items: [] }, "GET /v1/departments": DEPARTMENTS });
    renderPage();
    expect(await screen.findByText("No tickets yet")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Search"), "nothing");
    expect(await screen.findByText("No tickets match these filters")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: /clear filters/i })[0]!);
    expect(await screen.findByText("No tickets yet")).toBeInTheDocument();
  });

  it("filters by status through the API query and keeps the filter in the URL", async () => {
    const user = userEvent.setup();
    const { state, fetchMock } = setup();
    state.tickets[1]!.status = "in_progress";
    renderPage();
    await screen.findByText("EX-1001");
    await user.selectOptions(screen.getByLabelText("Status"), "in_progress");
    await waitFor(() => expect(screen.queryByText("EX-1001")).not.toBeInTheDocument());
    expect(screen.getByText("AC-1002")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("status=in_progress");
    const last = calls(fetchMock, "GET", "/v1/tickets").at(-1)!;
    expect(new URL(String(last[0]), "http://localhost").searchParams.get("status")).toBe("in_progress");
  });

  it("filters by department (options come from the departments config) and by priority", async () => {
    const user = userEvent.setup();
    setup();
    renderPage();
    await screen.findByText("EX-1001");
    const department = screen.getByLabelText("Department");
    await within(department).findByRole("option", { name: "Hostel" });
    await user.selectOptions(department, "hostel");
    await waitFor(() => expect(screen.queryByText("EX-1001")).not.toBeInTheDocument());
    expect(screen.getByText("HO-1003")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Priority"), "P1");
    expect(await screen.findByText("No tickets match these filters")).toBeInTheDocument();
  });

  it("searches summary and ticket id on the client without a new request", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();
    renderPage();
    await screen.findByText("EX-1001");
    const before = calls(fetchMock, "GET", "/v1/tickets").length;
    await user.type(screen.getByLabelText("Search"), "water");
    await waitFor(() => expect(screen.queryByText("EX-1001")).not.toBeInTheDocument());
    expect(screen.getByText("HO-1003")).toBeInTheDocument();
    expect(screen.getByText("1 of 4 tickets")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Search"));
    await user.type(screen.getByLabelText("Search"), "ac-1002");
    await waitFor(() => expect(screen.queryByText("HO-1003")).not.toBeInTheDocument());
    expect(screen.getByText("AC-1002")).toBeInTheDocument();
    expect(calls(fetchMock, "GET", "/v1/tickets").length).toBe(before);
  });

  it("refreshes the list when ticket.created arrives on the stream", async () => {
    const { state } = setup();
    renderWithProviders(<TicketsPage />, { withStream: true });
    await screen.findByText("EX-1001");
    FakeEventSource.last().open();
    state.tickets.push(ticket({ ticket_id: "EX-1099", priority: "P1", summary: "Brand new emergency" }));
    act(() => {
      FakeEventSource.last().emit("ticket.created", { ts: NOW, ticket_id: "EX-1099" });
    });
    expect(await screen.findByText("Brand new emergency")).toBeInTheDocument();
  });

  it("refreshes an open drawer when ticket.updated arrives for it", async () => {
    const { state } = setup();
    renderWithProviders(<TicketsPage />, { route: "/tickets?ticket=EX-1001", withStream: true });
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    FakeEventSource.last().open();
    state.tickets[0]!.summary = "Changed elsewhere";
    state.tickets[0]!.status = "resolved";
    act(() => {
      FakeEventSource.last().emit("ticket.updated", { ts: NOW, ticket_id: "EX-1001", status: "resolved" });
    });
    expect(await within(dialog).findByText("Changed elsewhere")).toBeInTheDocument();
  });
});

describe("ticket drawer", () => {
  it("opens from a row click, puts the id in the URL, and closing removes it", async () => {
    const user = userEvent.setup();
    setup();
    renderPage();
    await user.click(await screen.findByText("Cannot find exam room"));
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    expect(screen.getByTestId("location")).toHaveTextContent("ticket=EX-1001");
    expect(await within(dialog).findByText("Student is at the gate and cannot find hall B.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Close panel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByTestId("location")).not.toHaveTextContent("ticket=");
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    setup();
    renderPage("/tickets?ticket=EX-1001");
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("opens directly from /tickets?ticket=<id> and shows brief, rule badge, reason and collected fields", async () => {
    setup();
    renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    expect(await within(dialog).findByText("Cannot find exam room")).toBeInTheDocument();
    expect(within(dialog).getByText("Student is at the gate and cannot find hall B.")).toBeInTheDocument();
    expect(within(dialog).getByTestId("rule-id")).toHaveTextContent("R-EXAM-60");
    expect(within(dialog).getByText("exam in 15 min")).toBeInTheDocument();
    expect(within(dialog).getByText("21CS042")).toBeInTheDocument();
    expect(within(dialog).getByText("Maths")).toBeInTheDocument();
    expect(within(dialog).getByText("Caller: where is hall B")).toBeInTheDocument();
  });

  it("shows no rule badge when the reason has no rule id", async () => {
    setup();
    renderPage("/tickets?ticket=AC-1002");
    const dialog = await screen.findByRole("dialog", { name: "AC-1002" });
    expect(await within(dialog).findByText("No rule matched")).toBeInTheDocument();
    expect(within(dialog).queryByTestId("rule-id")).not.toBeInTheDocument();
  });

  it("shows an error state when the ticket does not exist", async () => {
    mockFetch({
      "GET /v1/tickets": { items: [] },
      "GET /v1/departments": DEPARTMENTS,
      "GET /v1/tickets/NOPE-1": errorResponse(404, "not_found", "Ticket NOPE-1 not found"),
      "GET /v1/tickets/NOPE-1/events": errorResponse(404, "not_found", "Ticket NOPE-1 not found"),
    });
    renderPage("/tickets?ticket=NOPE-1");
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Could not load the ticket")).toBeInTheDocument();
  });

  it("keeps numbers masked until Reveal is clicked, then refetches with reveal=true and notes the audit", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();
    renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    expect(within(dialog).getAllByTestId("masked-number").map((n) => n.textContent)).toEqual([MASKED, "+91•••••0003"]);
    const revealCalls = () => calls(fetchMock, "GET", "/v1/tickets/EX-1001").filter(([input]) => String(input).includes("reveal=true"));
    expect(revealCalls()).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Reveal numbers" }));
    await waitFor(() => expect(within(dialog).getAllByTestId("masked-number").map((n) => n.textContent)).toEqual([FULL, "+919876500003"]));
    expect(revealCalls()).toHaveLength(1);
    expect(within(dialog).getByText(/revealed, access recorded in the audit log/i)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Hide numbers" }));
    await waitFor(() => expect(within(dialog).getAllByTestId("masked-number")[0]).toHaveTextContent(MASKED));
    expect(within(dialog).queryByText(/revealed, access recorded/i)).not.toBeInTheDocument();
  });

  it("hides revealed numbers again after the drawer is closed and reopened", async () => {
    const user = userEvent.setup();
    setup();
    renderPage("/tickets?ticket=EX-1001");
    let dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    await user.click(within(dialog).getByRole("button", { name: "Reveal numbers" }));
    await waitFor(() => expect(within(dialog).getAllByTestId("masked-number")[0]).toHaveTextContent(FULL));
    await user.click(within(dialog).getByRole("button", { name: "Close panel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(screen.getByText("Cannot find exam room"));
    dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Student is at the gate and cannot find hall B.");
    expect(within(dialog).getAllByTestId("masked-number")[0]).toHaveTextContent(MASKED);
    expect(within(dialog).getByRole("button", { name: "Reveal numbers" })).toBeInTheDocument();
  });

  it("loads the transcript only after the section is opened", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();
    renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    await within(dialog).findByRole("list", { name: "Ticket events" });
    expect(calls(fetchMock, "GET", "/v1/calls/call-1")).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Show transcript" }));
    expect(await within(dialog).findByText("Exam hall kahan hai?")).toBeInTheDocument();
    expect(within(dialog).getByText("Hall B, second floor.")).toBeInTheDocument();
    expect(within(dialog).getByText("path: Escalation")).toBeInTheDocument();
    expect(calls(fetchMock, "GET", "/v1/calls/call-1")).toHaveLength(1);
    expect(within(dialog).getByRole("link", { name: /open call call-1/i })).toHaveAttribute("href", "/calls?call=call-1");
  });

  it("explains that a ticket without a call has no transcript", async () => {
    setup();
    renderPage("/tickets?ticket=AC-1002");
    const dialog = await screen.findByRole("dialog", { name: "AC-1002" });
    expect(await within(dialog).findByText(/no call is linked/i)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /transcript/i })).not.toBeInTheDocument();
  });

  it("shows an inline error when the transcript cannot be loaded", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /v1/tickets": { items: [p1] },
      "GET /v1/departments": DEPARTMENTS,
      "GET /v1/tickets/EX-1001": p1,
      "GET /v1/tickets/EX-1001/events": { items: [] },
      "GET /v1/calls/call-1": errorResponse(500, "internal", "transcript store down"),
    });
    renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    await user.click(within(dialog).getByRole("button", { name: "Show transcript" }));
    expect(await within(dialog).findByText(/transcript store down/)).toBeInTheDocument();
  });
});

describe("events timeline", () => {
  it("renders transfers, SMS with mock and live badges, status changes and notes, newest last", async () => {
    setup();
    renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    const timeline = await within(dialog).findByRole("list", { name: "Ticket events" });
    const items = within(timeline).getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("data-event-kind"))).toEqual([
      "transfer_attempted",
      "transfer_failed",
      "sms_sent",
      "sms_sent",
      "sms_suppressed",
      "status_changed",
      "note_added",
    ]);
    expect(within(timeline).getAllByText("SMS (mock)")).toHaveLength(2);
    expect(within(timeline).getByText("SMS (live)")).toBeInTheDocument();
    expect(within(items[2]!).getByText("status_change")).toBeInTheDocument();
    expect(within(items[2]!).getByText("+91•••••0003")).toBeInTheDocument();
    expect(within(items[4]!).getByText(/no_consent/)).toBeInTheDocument();
    expect(within(items[0]!).getByText("+91•••••7890")).toBeInTheDocument(); // phone-like payload values are masked
    expect(within(items[1]!).getByText("no_answer")).toBeInTheDocument();
    expect(within(items[5]!).getByText("Open")).toBeInTheDocument();
    expect(within(items[5]!).getByText("In progress")).toBeInTheDocument();
    expect(within(items[6]!).getByText("Called the student")).toBeInTheDocument();
    expect(within(items[6]!).getByText(/ago$/)).toBeInTheDocument();
  });

  it("shows an empty timeline and an error timeline", async () => {
    setup({ events: [] });
    const { unmount } = renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    expect(await within(dialog).findByText("No events yet")).toBeInTheDocument();
    unmount();
    vi.unstubAllGlobals();

    mockFetch({
      "GET /v1/tickets": { items: [p1] },
      "GET /v1/departments": DEPARTMENTS,
      "GET /v1/tickets/EX-1001": p1,
      "GET /v1/tickets/EX-1001/events": errorResponse(500, "internal", "events broke"),
    });
    renderPage("/tickets?ticket=EX-1001");
    const dialog2 = await screen.findByRole("dialog", { name: "EX-1001" });
    expect(await within(dialog2).findByText(/events broke/)).toBeInTheDocument();
  });
});

describe("updating a ticket", () => {
  it("PATCHes only the status, refreshes list and timeline, and shows the SMS hint when a call and callback number exist", async () => {
    const user = userEvent.setup();
    const { patches, fetchMock } = setup();
    renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    const listCalls = calls(fetchMock, "GET", "/v1/tickets").length;
    const eventCalls = calls(fetchMock, "GET", "/v1/tickets/EX-1001/events").length;
    const apply = within(dialog).getByRole("button", { name: "Save resolution" });
    expect(apply).toBeDisabled(); // nothing changed yet

    await user.selectOptions(within(dialog).getByLabelText("Status"), "in_progress");
    await user.click(within(dialog).getByRole("button", { name: "Apply status" }));

    await waitFor(() => expect(patches).toEqual([{ status: "in_progress" }]));
    expect(await within(dialog).findByTestId("sms-hint")).toHaveTextContent(/status SMS/i);
    await waitFor(() => expect(calls(fetchMock, "GET", "/v1/tickets").length).toBeGreaterThan(listCalls));
    await waitFor(() => expect(calls(fetchMock, "GET", "/v1/tickets/EX-1001/events").length).toBeGreaterThan(eventCalls));
    // the table behind the drawer shows the new status
    const row = document.querySelector('[data-row-key="EX-1001"]') as HTMLElement;
    await waitFor(() => expect(within(row).getByText("In progress")).toBeInTheDocument());
  });

  it("does not promise an SMS for a ticket without a call", async () => {
    const user = userEvent.setup();
    const { patches } = setup();
    renderPage("/tickets?ticket=AC-1002");
    const dialog = await screen.findByRole("dialog", { name: "AC-1002" });
    await within(dialog).findByText("Fee deadline today");
    await user.selectOptions(within(dialog).getByLabelText("Status"), "in_progress");
    await user.click(within(dialog).getByRole("button", { name: "Apply status" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    await within(dialog).findByText("Status set to In progress.");
    expect(within(dialog).queryByTestId("sms-hint")).not.toBeInTheDocument();
  });

  it("offers a resolution field when resolving and sends it with the status", async () => {
    const user = userEvent.setup();
    const { patches } = setup();
    renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    expect(within(dialog).queryByLabelText("Resolution")).not.toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText("Status"), "resolved");
    await user.type(within(dialog).getByLabelText("Resolution"), "Guided the student to hall B");
    await user.click(within(dialog).getByRole("button", { name: "Apply status" }));
    await waitFor(() => expect(patches).toEqual([{ status: "resolved", resolution: "Guided the student to hall B" }]));
  });

  it("appends a note via PATCH note and clears the field", async () => {
    const user = userEvent.setup();
    const { patches } = setup();
    renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    const add = within(dialog).getByRole("button", { name: "Add note" });
    expect(add).toBeDisabled();
    await user.type(within(dialog).getByLabelText("New note"), "Spoke to the proctor");
    await user.click(add);
    await waitFor(() => expect(patches).toEqual([{ note: "Spoke to the proctor" }]));
    const notes = await within(dialog).findByRole("list", { name: "Notes" });
    expect(within(notes).getByText("Spoke to the proctor")).toBeInTheDocument();
    expect(within(notes).getByText("exam@demo")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("New note")).toHaveValue("");
    expect(within(dialog).queryByTestId("sms-hint")).not.toBeInTheDocument();
  });

  it("changes the assignee, with an Assign to me shortcut from the cached session", async () => {
    const user = userEvent.setup();
    const { patches } = setup();
    const client = testQueryClient();
    client.setQueryData(qk.me, { email: "exam@demo", role: "staff", department: "exam_cell" });
    renderPage("/tickets?ticket=EX-1001", client);
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    expect(within(dialog).getByRole("button", { name: "Save assignee" })).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Assign to me" }));
    expect(within(dialog).getByLabelText("Assignee")).toHaveValue("exam@demo");
    await user.click(within(dialog).getByRole("button", { name: "Save assignee" }));
    await waitFor(() => expect(patches).toEqual([{ assignee: "exam@demo" }]));
    await within(dialog).findByText("Assigned to exam@demo.");
    expect(within(dialog).queryByRole("button", { name: "Assign to me" })).not.toBeInTheDocument();
  });

  it("shows the API error inline and leaves the controls usable", async () => {
    const user = userEvent.setup();
    setup({ patchError: true });
    renderPage("/tickets?ticket=EX-1001");
    const dialog = await screen.findByRole("dialog", { name: "EX-1001" });
    await within(dialog).findByText("Cannot find exam room");
    await user.type(within(dialog).getByLabelText("New note"), "will fail");
    await user.click(within(dialog).getByRole("button", { name: "Add note" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Database is busy");
    expect(within(dialog).getByLabelText("New note")).toHaveValue("will fail");
    expect(within(dialog).getByRole("button", { name: "Add note" })).toBeEnabled();
  });
});

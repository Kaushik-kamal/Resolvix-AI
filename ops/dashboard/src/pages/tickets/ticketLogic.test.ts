import { describe, expect, it } from "vitest";
import type { TicketEventRow, TicketRow } from "../../api/extra";
import {
  buildStatusPatch,
  EMPTY_FILTERS,
  filterTickets,
  matchesSearch,
  mayTriggerSms,
  parseNote,
  parsePriorityReason,
  payloadEntries,
  safePayloadValue,
  sortEvents,
} from "./ticketLogic";

function ticket(partial: Partial<TicketRow> & Pick<TicketRow, "ticket_id" | "priority">): TicketRow {
  return {
    call_id: null,
    type: "URGENT",
    priority_reason: "R-EXAM-60: exam soon",
    department: "exam_cell",
    status: "open",
    summary: "Summary",
    collected_fields: {},
    caller_number: "+91•••••0002",
    callback_number: null,
    callback_requested: false,
    transcript_excerpt: "",
    brief: "",
    assignee: null,
    notes: [],
    created_at: "2026-10-31T10:00:00+00:00",
    updated_at: "2026-10-31T10:00:00+00:00",
    resolved_at: null,
    ...partial,
  };
}

const tickets = [
  ticket({ ticket_id: "HO-1003", priority: "P3", department: "hostel", summary: "Water heater broken", created_at: "2026-10-31T09:00:00+00:00" }),
  ticket({ ticket_id: "EX-1001", priority: "P1", summary: "Cannot find exam room", created_at: "2026-10-31T08:00:00+00:00" }),
  ticket({ ticket_id: "AC-1002", priority: "P2", department: "accounts", summary: "Fee deadline today", status: "in_progress" }),
  ticket({ ticket_id: "EX-1004", priority: "P1", summary: "Admit card missing", created_at: "2026-10-31T09:30:00+00:00" }),
];

describe("filterTickets", () => {
  it("sorts P1 to P4, newest first inside a priority", () => {
    expect(filterTickets(tickets, EMPTY_FILTERS).map((t) => t.ticket_id)).toEqual(["EX-1004", "EX-1001", "AC-1002", "HO-1003"]);
  });

  it("filters by status, department and priority", () => {
    expect(filterTickets(tickets, { ...EMPTY_FILTERS, status: "in_progress" }).map((t) => t.ticket_id)).toEqual(["AC-1002"]);
    expect(filterTickets(tickets, { ...EMPTY_FILTERS, department: "hostel" }).map((t) => t.ticket_id)).toEqual(["HO-1003"]);
    expect(filterTickets(tickets, { ...EMPTY_FILTERS, priority: "P1" }).map((t) => t.ticket_id)).toEqual(["EX-1004", "EX-1001"]);
    expect(filterTickets(tickets, { status: "open", department: "exam_cell", priority: "P1", query: "" })).toHaveLength(2);
  });

  it("does not mutate its input", () => {
    const copy = [...tickets];
    filterTickets(tickets, { ...EMPTY_FILTERS, priority: "P1" });
    expect(tickets).toEqual(copy);
  });
});

describe("matchesSearch", () => {
  const t = tickets[1]!;
  it("matches summary, ticket id and department, case-insensitively", () => {
    expect(matchesSearch(t, "exam room")).toBe(true);
    expect(matchesSearch(t, "ex-1001")).toBe(true);
    expect(matchesSearch(t, "EXAM cell")).toBe(true);
    expect(matchesSearch(t, "exam_cell")).toBe(true);
  });
  it("needs every word to match", () => {
    expect(matchesSearch(t, "exam hostel")).toBe(false);
  });
  it("blank query matches everything; the masked caller number is not searched", () => {
    expect(matchesSearch(t, "   ")).toBe(true);
    expect(matchesSearch(t, "0002")).toBe(false);
  });
});

describe("parsePriorityReason", () => {
  it("splits the rule id from the text", () => {
    expect(parsePriorityReason("R-EXAM-60: exam in 15 min")).toEqual({ ruleId: "R-EXAM-60", text: "exam in 15 min" });
    expect(parsePriorityReason("R-SAFETY-1 - student unsafe")).toEqual({ ruleId: "R-SAFETY-1", text: "student unsafe" });
  });
  it("keeps a reason without a rule id as text", () => {
    expect(parsePriorityReason("Routine question")).toEqual({ ruleId: null, text: "Routine question" });
    expect(parsePriorityReason("")).toEqual({ ruleId: null, text: "" });
    expect(parsePriorityReason(null)).toEqual({ ruleId: null, text: "" });
  });
});

describe("parseNote", () => {
  it("parses [iso] actor: text", () => {
    expect(parseNote("[2026-10-31T10:00:00+00:00] exam@demo: called back: all fine")).toEqual({
      at: "2026-10-31T10:00:00+00:00",
      actor: "exam@demo",
      text: "called back: all fine",
    });
  });
  it("falls back to plain text", () => {
    expect(parseNote("just a note")).toEqual({ at: null, actor: null, text: "just a note" });
  });
});

describe("events helpers", () => {
  const event = (at: string, kind: TicketEventRow["kind"]): TicketEventRow => ({ at, kind, actor: "x", payload: {} });
  it("sorts events oldest first without mutating", () => {
    const input = [event("2026-10-31T10:05:00+00:00", "note_added"), event("2026-10-31T10:00:00+00:00", "sms_sent")];
    expect(sortEvents(input).map((e) => e.kind)).toEqual(["sms_sent", "note_added"]);
    expect(input[0]!.kind).toBe("note_added");
  });
  it("masks phone-like payload values and drops empty or skipped keys", () => {
    expect(safePayloadValue("+919876543210")).toBe("+91•••••3210");
    expect(safePayloadValue("status_change")).toBe("status_change");
    expect(payloadEntries({ a: "1", b: "", c: "+911234567890", skip: "x" }, ["skip"])).toEqual([
      ["a", "1"],
      ["c", "+91•••••7890"],
    ]);
  });
});

describe("patch helpers", () => {
  it("sends only changed fields", () => {
    expect(buildStatusPatch({ currentStatus: "open", nextStatus: "open", resolution: "" })).toEqual({});
    expect(buildStatusPatch({ currentStatus: "open", nextStatus: "in_progress", resolution: "ignored" })).toEqual({ status: "in_progress" });
    expect(buildStatusPatch({ currentStatus: "open", nextStatus: "resolved", resolution: "  fixed  " })).toEqual({ status: "resolved", resolution: "fixed" });
    expect(buildStatusPatch({ currentStatus: "resolved", nextStatus: "resolved", resolution: "late note" })).toEqual({ resolution: "late note" });
  });
  it("SMS hint needs a call and a callback number", () => {
    expect(mayTriggerSms({ call_id: "c1", callback_number: "+91•••••0002" })).toBe(true);
    expect(mayTriggerSms({ call_id: null, callback_number: "+91•••••0002" })).toBe(false);
    expect(mayTriggerSms({ call_id: "c1", callback_number: null })).toBe(false);
  });
});

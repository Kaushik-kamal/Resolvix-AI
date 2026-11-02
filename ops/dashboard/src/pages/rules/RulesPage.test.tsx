import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorResponse, mockFetch, renderWithProviders } from "../../test/utils";
import { DEPARTMENTS } from "../kb/testUtils";
import RulesPage from "./RulesPage";
import { conditionsOf, formatDays, formatHours, rulesDocView } from "./rulesModel";

afterEach(() => {
  vi.unstubAllGlobals();
});

const RULES = {
  version: 1,
  rules: [
    {
      id: "R-EXAM-60",
      when: { event_type: "exam", minutes_to_event_lte: 60, blocked: true },
      priority: "P1",
      ticket_type: "URGENT",
      department: "exam_cell",
      action: "transfer_now",
      reason: "Exam within 60 minutes and caller blocked",
    },
    {
      id: "R-DEADLINE-24H",
      when: { event_type_in: ["fee_deadline", "form_deadline"], minutes_to_event_lte: 1440 },
      priority: "P2",
      ticket_type: "URGENT",
      department: "from_event",
      action: "transfer_if_open_else_callback",
      reason: "Deadline within 24 hours",
    },
    { id: "R-ROUTINE", when: {}, priority: "P4", ticket_type: null, action: "none", reason: "Routine information" },
  ],
  safety_lexicon: { medical: ["ambulance", "बेहोश"], harassment: ["ragging"] },
  human_request_lexicon: ["human", "operator"],
};

describe("rulesModel", () => {
  it("turns operator suffixes into readable conditions", () => {
    expect(conditionsOf({ minutes_to_event_lte: 60, event_type_in: ["a", "b"], blocked: true, score_gte: 3, x_not_in: [1] })).toEqual([
      { field: "minutes_to_event", op: "≤", value: "60" },
      { field: "event_type", op: "in", value: "a, b" },
      { field: "blocked", op: "=", value: "true" },
      { field: "score", op: "≥", value: "3" },
      { field: "x", op: "not in", value: "1" },
    ]);
    expect(conditionsOf({})).toEqual([]);
    expect(conditionsOf(undefined)).toEqual([]);
    expect(conditionsOf("weird")).toEqual([{ field: "when", op: "=", value: "weird" }]);
  });

  it("compresses day lists and formats hours", () => {
    expect(formatDays(["mon", "tue", "wed", "thu", "fri"])).toBe("Mon–Fri");
    expect(formatDays(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])).toBe("Mon–Sun");
    expect(formatDays(["sat"])).toBe("Sat");
    expect(formatDays(["mon", "wed"])).toBe("Mon, Wed");
    expect(formatDays(["mon", "tue"])).toBe("Mon, Tue");
    expect(formatDays(["fri", "mon", "tue", "someday"])).toBe("Mon, Tue, Fri, someday");
    expect(formatHours([{ days: ["sat"], open: "09:00", close: "13:00" }])).toEqual(["Sat 09:00–13:00"]);
    expect(formatHours(undefined)).toEqual([]);
  });

  it("survives a malformed document", () => {
    expect(rulesDocView(null)).toMatchObject({ malformed: true, rules: [] });
    expect(rulesDocView({ rules: "nope" })).toMatchObject({ malformed: true, rules: [] });
    const view = rulesDocView({ version: 2, rules: [42, { priority: "P9", mystery: { a: 1 } }] });
    expect(view.malformed).toBe(false);
    expect(view.rules[0]).toMatchObject({ id: "(rule 1)", priority: null, extras: [["value", "42"]] });
    expect(view.rules[1]).toMatchObject({ id: "(rule 2)", priority: null, rawPriority: "P9", extras: [["mystery", '{"a":1}']] });
  });
});

describe("Rules page", () => {
  it("renders the urgency rules in order with priority, conditions, department, action and reason", async () => {
    mockFetch({ "GET /v1/urgency-rules": RULES, "GET /v1/departments": DEPARTMENTS });
    renderWithProviders(<RulesPage />);
    await screen.findByText("R-EXAM-60");

    const rows = Array.from(document.querySelectorAll("tbody tr")).filter((r) => (r.getAttribute("data-row-key") ?? "").includes("-R-"));
    expect(rows.map((r) => r.getAttribute("data-row-key"))).toEqual(["1-R-EXAM-60", "2-R-DEADLINE-24H", "3-R-ROUTINE"]);

    const exam = within(rows[0] as HTMLElement);
    expect(exam.getByLabelText("Priority P1")).toBeInTheDocument();
    expect(exam.getByText(/minutes_to_event/)).toBeInTheDocument();
    expect(exam.getByText(/≤\s*60/)).toBeInTheDocument();
    expect(exam.getByText("exam_cell")).toBeInTheDocument();
    expect(exam.getByText("transfer_now")).toBeInTheDocument();
    expect(exam.getByText("Exam within 60 minutes and caller blocked")).toBeInTheDocument();

    const deadline = within(rows[1] as HTMLElement);
    expect(deadline.getByText(/fee_deadline, form_deadline/)).toBeInTheDocument();
    expect(deadline.getByLabelText("Priority P2")).toBeInTheDocument();

    const routine = within(rows[2] as HTMLElement);
    expect(routine.getByText(/Always/)).toBeInTheDocument();
    expect(routine.getByLabelText("Priority P4")).toBeInTheDocument();

    expect(screen.getByText("Urgency rules (version 1)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit|save|delete/i })).not.toBeInTheDocument();
  });

  it("shows the lexicons from the rules file", async () => {
    mockFetch({ "GET /v1/urgency-rules": RULES, "GET /v1/departments": DEPARTMENTS });
    renderWithProviders(<RulesPage />);
    await screen.findByText("R-EXAM-60");
    expect(screen.getByText("Safety lexicon")).toBeInTheDocument();
    expect(screen.getByText("ambulance")).toBeInTheDocument();
    expect(screen.getByText("Human request lexicon")).toBeInTheDocument();
    expect(screen.getByText("operator")).toBeInTheDocument();
  });

  it("renders a rule shape it does not know without crashing", async () => {
    mockFetch({
      "GET /v1/urgency-rules": {
        version: 3,
        rules: [
          { id: "R-NEW", when: ["not", "an", "object"], priority: "P9", weight: 0.7, tags: ["a", "b"], reason: { en: "nested" } },
          "just a string",
          { when: { flag: null } },
        ],
        future_section: { limits: { max_p1: 5 } },
      },
      "GET /v1/departments": DEPARTMENTS,
    });
    renderWithProviders(<RulesPage />);
    expect(await screen.findByText("R-NEW")).toBeInTheDocument();
    expect(screen.getByText("P9")).toBeInTheDocument();
    expect(screen.getByText("Other fields")).toBeInTheDocument();
    expect(screen.getByText("weight").closest("li")).toHaveTextContent("weight: 0.7");
    expect(screen.getByText("tags").closest("li")).toHaveTextContent("tags: a, b");
    expect(screen.getByText("value").closest("li")).toHaveTextContent("value: just a string");
    expect(screen.getByText("(rule 3)")).toBeInTheDocument();
    expect(screen.getByText("Future section")).toBeInTheDocument();
  });

  it("warns when the rules list is missing", async () => {
    mockFetch({ "GET /v1/urgency-rules": { version: 1 }, "GET /v1/departments": DEPARTMENTS });
    renderWithProviders(<RulesPage />);
    expect(await screen.findByText(/no list called/)).toBeInTheDocument();
    expect(screen.getByText("No urgency rules")).toBeInTheDocument();
  });

  it("renders departments with hours, masked numbers and topics", async () => {
    mockFetch({ "GET /v1/urgency-rules": RULES, "GET /v1/departments": DEPARTMENTS });
    renderWithProviders(<RulesPage />);
    await screen.findByText("Examination Cell");

    const exam = within(document.querySelector('tr[data-row-key="exam_cell"]') as HTMLElement);
    expect(exam.getByText("Mon–Fri 09:00–17:00")).toBeInTheDocument();
    expect(exam.getByText("Sat 09:00–13:00")).toBeInTheDocument();
    expect(exam.getByText("EX")).toBeInTheDocument();
    expect(exam.getByText("admit card")).toBeInTheDocument();
    // two transfer numbers + one alert number, all masked; the full numbers never appear
    const masked = exam.getAllByTestId("masked-number").map((n) => n.textContent);
    expect(masked).toEqual(["+91•••••0101", "+91•••••0102", "+91•••••0101"]);
    expect(screen.queryByText("+910000000101")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reveal/i })).not.toBeInTheDocument();

    const transport = within(document.querySelector('tr[data-row-key="transport"]') as HTMLElement);
    expect(transport.getByText("Not set")).toBeInTheDocument();
    expect(transport.getByText(/Data only/)).toBeInTheDocument();

    // summary: default department and the public emergency number (not masked)
    expect(screen.getByText("helpdesk")).toBeInTheDocument();
    expect(screen.getByText("112")).toBeInTheDocument();
  });

  it("shows numbers the API already masked for a non-admin session as they are (no double masking), 112 stays plain", async () => {
    const masked = {
      ...DEPARTMENTS,
      departments: DEPARTMENTS.departments.map((d) => ({
        ...d,
        transfer_numbers: (d.transfer_numbers ?? []).map((n) => n.slice(0, 3) + "•••••" + n.slice(-4)),
        sms_alert_numbers: d.sms_alert_numbers ? d.sms_alert_numbers.map((n) => n.slice(0, 3) + "•••••" + n.slice(-4)) : d.sms_alert_numbers,
      })),
    };
    mockFetch({ "GET /v1/urgency-rules": RULES, "GET /v1/departments": masked });
    renderWithProviders(<RulesPage />);
    await screen.findByText("Examination Cell");
    const exam = within(document.querySelector('tr[data-row-key="exam_cell"]') as HTMLElement);
    // same text the API sent; a second masking pass would have produced "+91•••••••••0101" or "•••"
    expect(exam.getAllByTestId("masked-number").map((n) => n.textContent)).toEqual(["+91•••••0101", "+91•••••0102", "+91•••••0101"]);
    expect(document.body.textContent).not.toMatch(/•{6,}/);
    expect(screen.getByText("112")).toBeInTheDocument();
    expect(screen.queryAllByTestId("masked-number").every((n) => n.textContent !== "•••")).toBe(true);
  });

  it("shows error states per section and the loading state first", async () => {
    mockFetch({ "GET /v1/urgency-rules": errorResponse(500, "internal", "rules broke"), "GET /v1/departments": DEPARTMENTS });
    renderWithProviders(<RulesPage />);
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(await screen.findByText(/rules broke/)).toBeInTheDocument();
    // departments still render
    expect(await screen.findByText("Examination Cell")).toBeInTheDocument();
  });

  it("shows the empty department state", async () => {
    mockFetch({
      "GET /v1/urgency-rules": RULES,
      "GET /v1/departments": { ...DEPARTMENTS, departments: [] },
    });
    renderWithProviders(<RulesPage />);
    expect(await screen.findByText("No departments")).toBeInTheDocument();
  });

  it("renders R-FALLBACK and the human_request_exclusions section from the current urgency_rules.yaml", async () => {
    mockFetch({
      "GET /v1/urgency-rules": {
        version: 1,
        rules: [
          {
            id: "R-FALLBACK", when: { intent: "system_failure" }, priority: "P3", ticket_type: "SYSTEM_FAILURE",
            department: "from_topic_or_default", action: "ticket_and_callback",
            reason: "Agent could not answer because of a system failure",
          },
          { id: "R-ROUTINE", when: {}, priority: "P4", ticket_type: null, department: "from_topic", action: "answer" },
        ],
        safety_lexicon: { en: ["ambulance"] },
        human_request_lexicon: ["operator"],
        human_request_exclusions: ["human resource", "humanities"],
      },
      "GET /v1/departments": DEPARTMENTS,
    });
    renderWithProviders(<RulesPage />);
    expect(await screen.findByText("R-FALLBACK")).toBeInTheDocument();
    expect(screen.getByText("ticket_and_callback")).toBeInTheDocument();   // unknown action shown as plain text
    expect(screen.getByText("System failure")).toBeInTheDocument();         // readable ticket type
    expect(screen.getByText("Agent could not answer because of a system failure")).toBeInTheDocument();
    expect(screen.getByText("Human request exclusions")).toBeInTheDocument(); // extra top-level key, no crash
  });
});

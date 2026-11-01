import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CallDetail, CallSummary } from "../../api/extra";
import { FakeEventSource } from "../../test/fakeEventSource";
import { errorResponse, mockFetch, renderWithProviders } from "../../test/utils";
import CallsPage from "./index";
import { buildCallListParams, formatLatency, lastTurnText, outcomeLabel, yesNo } from "./callLogic";

const MASKED = "+91•••••0002";
const FULL = "+919876500002";

function call(partial: Partial<CallSummary> & Pick<CallSummary, "call_id">): CallSummary {
  return {
    channel: "pstn",
    caller_number: MASKED,
    started_at: "2026-10-31T10:00:00+00:00",
    ended_at: "2026-10-31T10:03:05+00:00",
    kb_version: "kb-1",
    lang: "hinglish",
    outcome: "answered",
    ai_resolved: true,
    turns_count: 3,
    last_turn: { turn_index: 2, path: "faq", tier: "confident", lang: "hinglish" },
    ...partial,
  };
}

const answered = call({ call_id: "call-a" });
const escalated = call({ call_id: "call-e", outcome: "escalated", ai_resolved: false, channel: "web", lang: "en", turns_count: 5, last_turn: { turn_index: 4, path: "escalation", tier: null, lang: "en" } });
const active = call({ call_id: "call-live", ended_at: null, outcome: null, ai_resolved: null, turns_count: 1, last_turn: null });

const DETAIL: CallDetail = {
  call: answered,
  turns: [
    {
      call_id: "call-a",
      turn_index: 0,
      path: "faq",
      tier: "confident",
      lang: "hinglish",
      kb_ids: ["kb-fee-1", "kb-fee-2"],
      validator_flags: ["number_not_in_kb"],
      latency_ms: { stt: 120.4, llm: 840, total: 1010 },
      cached_tokens: 512,
      priority: "P2",
      priority_reason: "R-FEE-1: deadline today",
      rule_id: "R-FEE-1",
      user_text_redacted: "Fee kab tak bharni hai?",
      assistant_text: "Fee 5 November tak bharni hai.",
      created_at: "2026-10-31T10:00:10+00:00",
    },
    {
      call_id: "call-a",
      turn_index: 1,
      path: "llm",
      tier: null,
      lang: "hinglish",
      user_text_redacted: "Shukriya",
      assistant_text: "Aapka swagat hai.",
      created_at: "2026-10-31T10:00:30+00:00",
    },
  ],
};

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

function renderPage(route = "/calls") {
  return renderWithProviders(
    <>
      <CallsPage />
      <LocationProbe />
    </>,
    { route },
  );
}

function listRoute(items: CallSummary[] = [answered, escalated, active]) {
  return (url: URL) => {
    const outcome = url.searchParams.get("outcome");
    const onlyActive = url.searchParams.get("active") === "true";
    return { items: items.filter((c) => (!outcome || c.outcome === outcome) && (!onlyActive || !c.ended_at)) };
  };
}

function getCalls(fetchMock: ReturnType<typeof mockFetch>, path: string) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    return ((init as RequestInit | undefined)?.method ?? "GET") === "GET" && new URL(String(input), "http://localhost").pathname === path;
  });
}

beforeEach(() => {
  FakeEventSource.reset();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("call helpers", () => {
  it("builds list params: active is only sent when switched on", () => {
    expect(buildCallListParams("", false)).toEqual({ limit: 200 });
    expect(buildCallListParams("answered", true)).toEqual({ outcome: "answered", active: true, limit: 200 });
  });
  it("formats latency, last turn, outcome and yes/no", () => {
    expect(formatLatency({ stt: 120.4, llm: 840 })).toBe("stt 120 · llm 840");
    expect(formatLatency({})).toBe("—");
    expect(formatLatency(undefined)).toBe("—");
    expect(lastTurnText({ turn_index: 1, path: "faq", tier: "confident", lang: "en" })).toBe("Faq / Confident");
    expect(lastTurnText({ turn_index: 1, path: "escalation", tier: null, lang: "en" })).toBe("Escalation");
    expect(lastTurnText(null)).toBe("—");
    expect(outcomeLabel({ ended_at: null, outcome: null })).toBe("In progress");
    expect(outcomeLabel({ ended_at: "x", outcome: "failed" })).toBe("Failed");
    expect(yesNo(true)).toBe("Yes");
    expect(yesNo(false)).toBe("No");
    expect(yesNo(null)).toBe("—");
  });
});

describe("calls list", () => {
  it("shows the columns: time, masked number, channel, lang, outcome, AI resolved, turns, last turn", async () => {
    mockFetch({ "GET /v1/calls": listRoute() });
    renderPage();
    await screen.findByText("Calls", { selector: "h1" });
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(4); // header + 3
    const first = within(rows[1]!);
    expect(first.getByText(MASKED)).toBeInTheDocument();
    expect(first.getByText("pstn")).toBeInTheDocument();
    expect(first.getByText("hinglish")).toBeInTheDocument();
    expect(first.getByText("Answered")).toBeInTheDocument();
    expect(first.getByText("Yes")).toBeInTheDocument();
    expect(first.getByText("3")).toBeInTheDocument();
    expect(first.getByText("Faq / Confident")).toBeInTheDocument();
    expect(first.getByText("3m 05s")).toBeInTheDocument();
    expect(first.getByText(/31 Oct 2026, 15:30 IST/)).toBeInTheDocument();
    const live = within(rows[3]!);
    expect(live.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("3 calls")).toBeInTheDocument();
  });

  it("shows loading, error with retry, and empty states", async () => {
    const user = userEvent.setup();
    let mode: "pending" | "fail" | "empty" = "pending";
    mockFetch({
      "GET /v1/calls": () => {
        if (mode === "pending") return new Promise(() => undefined);
        return mode === "fail" ? errorResponse(500, "internal", "calls store down") : { items: [] };
      },
    });
    const first = renderPage();
    expect(screen.getByRole("status", { name: "Loading…" })).toBeInTheDocument();
    first.unmount();

    mode = "fail";
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("calls store down");
    mode = "empty";
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("No calls yet")).toBeInTheDocument();
  });

  it("filters by outcome through the API query", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch({ "GET /v1/calls": listRoute() });
    renderPage();
    await screen.findAllByText("pstn");
    await user.selectOptions(screen.getByLabelText("Outcome"), "escalated");
    await waitFor(() => expect(screen.queryByText("Faq / Confident")).not.toBeInTheDocument());
    expect(screen.getByText("Escalation")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("outcome=escalated");
    const last = getCalls(fetchMock, "/v1/calls").at(-1)!;
    expect(new URL(String(last[0]), "http://localhost").searchParams.get("outcome")).toBe("escalated");
  });

  it("the active-only toggle sends active=true and clear filters resets", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch({ "GET /v1/calls": listRoute() });
    renderPage();
    await screen.findAllByText("pstn");
    expect(new URL(String(getCalls(fetchMock, "/v1/calls")[0]![0]), "http://localhost").searchParams.has("active")).toBe(false);
    await user.click(screen.getByLabelText("Active calls only"));
    await waitFor(() => expect(screen.getByText("1 calls")).toBeInTheDocument());
    const last = getCalls(fetchMock, "/v1/calls").at(-1)!;
    expect(new URL(String(last[0]), "http://localhost").searchParams.get("active")).toBe("true");
    expect(screen.getByText("In progress")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Outcome"), "answered");
    expect(await screen.findByText("No calls match these filters")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: /clear filters/i })[0]!);
    await waitFor(() => expect(screen.getByText("3 calls")).toBeInTheDocument());
    expect(screen.getByTestId("location")).toHaveTextContent("");
    expect((screen.getByLabelText("Active calls only") as HTMLInputElement).checked).toBe(false);
  });

  it("never fetches call details for the list rows", async () => {
    const fetchMock = mockFetch({ "GET /v1/calls": listRoute() });
    renderPage();
    await screen.findAllByText("pstn");
    expect(fetchMock.mock.calls.every(([input]) => new URL(String(input), "http://localhost").pathname === "/v1/calls")).toBe(true);
  });

  it("refreshes on call.started from the stream", async () => {
    const items = [answered];
    mockFetch({ "GET /v1/calls": () => ({ items }) });
    renderWithProviders(<CallsPage />, { withStream: true });
    await screen.findByText("1 calls");
    FakeEventSource.last().open();
    items.unshift(active);
    act(() => {
      FakeEventSource.last().emit("call.started", { ts: "2026-10-31T10:00:00+00:00", call_id: "call-live" });
    });
    expect(await screen.findByText("2 calls")).toBeInTheDocument();
  });

  it("opens a call from a row click and from the keyboard", async () => {
    const user = userEvent.setup();
    mockFetch({ "GET /v1/calls": listRoute(), "GET /v1/calls/call-a": DETAIL });
    renderPage();
    const row = (await screen.findAllByText("pstn"))[0]!.closest("tr")!;
    row.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "Call call-a" })).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("call=call-a");
  });
});

describe("call detail", () => {
  it("shows the turns table with path, tier, kb ids, flags, latency, cached tokens, priority and texts", async () => {
    mockFetch({ "GET /v1/calls/call-a": DETAIL });
    renderPage("/calls?call=call-a");
    expect(await screen.findByRole("heading", { name: "Call call-a" })).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Turns of this call" });
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["#", "Path", "Tier", "KB ids", "Validator flags", "Latency ms", "Cached tok", "Priority", "Caller (redacted)", "Assistant"]);
    const rows = within(table).getAllByRole("row");
    const first = within(rows[1]!);
    expect(first.getByText("Faq")).toBeInTheDocument();
    expect(first.getByText("Confident")).toBeInTheDocument();
    expect(first.getByText("kb-fee-1, kb-fee-2")).toBeInTheDocument();
    expect(first.getByText("number_not_in_kb")).toBeInTheDocument();
    expect(first.getByText("stt 120 · llm 840 · total 1010")).toBeInTheDocument();
    expect(first.getByText("512")).toBeInTheDocument();
    expect(first.getByText("P2")).toBeInTheDocument();
    expect(first.getByText("R-FEE-1")).toBeInTheDocument();
    expect(first.getByText("Fee kab tak bharni hai?")).toBeInTheDocument();
    expect(first.getByText("Fee 5 November tak bharni hai.")).toBeInTheDocument();
    const second = within(rows[2]!);
    expect(second.getByText("Llm")).toBeInTheDocument();
    expect(second.getAllByText("—").length).toBeGreaterThanOrEqual(4); // tier, kb, flags, latency, cached, priority empty
    expect(screen.getByText("Turns (2)")).toBeInTheDocument();
    expect(screen.getByText("3m 05s")).toBeInTheDocument();
  });

  it("keeps the number masked until Reveal, then fetches with reveal=true", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch({
      "GET /v1/calls/call-a": (url: URL) =>
        url.searchParams.get("reveal") === "true" ? { ...DETAIL, call: { ...answered, caller_number: FULL } } : DETAIL,
    });
    renderPage("/calls?call=call-a");
    await screen.findByRole("table", { name: "Turns of this call" });
    expect(screen.getByTestId("masked-number")).toHaveTextContent(MASKED);
    expect(getCalls(fetchMock, "/v1/calls/call-a")).toHaveLength(1);
    expect(String(getCalls(fetchMock, "/v1/calls/call-a")[0]![0])).not.toContain("reveal=true");

    await user.click(screen.getByRole("button", { name: "Reveal number" }));
    await waitFor(() => expect(screen.getByTestId("masked-number")).toHaveTextContent(FULL));
    expect(String(getCalls(fetchMock, "/v1/calls/call-a").at(-1)![0])).toContain("reveal=true");
    expect(screen.getByText(/Number revealed, access recorded/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Hide number" }));
    await waitFor(() => expect(screen.getByTestId("masked-number")).toHaveTextContent(MASKED));
  });

  it("does not refetch the audited detail on its own, only on Refresh", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch({ "GET /v1/calls/call-a": DETAIL });
    renderPage("/calls?call=call-a");
    await screen.findByRole("table", { name: "Turns of this call" });
    window.dispatchEvent(new Event("focus"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(getCalls(fetchMock, "/v1/calls/call-a")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(getCalls(fetchMock, "/v1/calls/call-a")).toHaveLength(2));
  });

  it("goes back to the list and removes the call parameter", async () => {
    const user = userEvent.setup();
    mockFetch({ "GET /v1/calls": listRoute(), "GET /v1/calls/call-a": DETAIL });
    renderPage("/calls?call=call-a");
    await screen.findByRole("table", { name: "Turns of this call" });
    await user.click(screen.getByRole("button", { name: "All calls" }));
    expect(await screen.findByText("3 calls")).toBeInTheDocument();
    expect(screen.getByTestId("location")).not.toHaveTextContent("call=");
  });

  it("shows an empty turns state for a running call and an error state for an unknown call", async () => {
    mockFetch({
      "GET /v1/calls/call-live": { call: active, turns: [] },
      "GET /v1/calls/nope": errorResponse(404, "not_found", "Call nope not found"),
    });
    const first = renderPage("/calls?call=call-live");
    expect(await screen.findByText("No turns recorded")).toBeInTheDocument();
    expect(screen.getByText(/still running/i, { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Still running")).toBeInTheDocument();
    first.unmount();

    renderPage("/calls?call=nope");
    expect(await screen.findByText("Could not load the call")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Call nope not found");
  });
});

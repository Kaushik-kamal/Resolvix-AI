import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { KBPublishRecord } from "../../api/extra";
import { errorResponse, mockFetch } from "../../test/utils";
import { buildTicketDraftSeed, KB_DRAFT_STATE_KEY, readDraftSeed } from "./draftSeed";
import KbPage from "./KbPage";
import { newestPublishMode } from "./PublishPanel";
import { ADMIN_ME, DEPARTMENTS, LocationProbe, STAFF_ME, entriesResponse, kbEntry, renderWithAuth, versionInfo } from "./testUtils";
import { valuesFromSeed } from "./kbModel";

afterEach(() => vi.unstubAllGlobals());

const ENTRIES = [kbEntry({ id: "FEE-101", status: "approved" }), kbEntry({ id: "FEE-102", status: "draft" })];

function routes(me = ADMIN_ME, extra: Record<string, unknown> = {}) {
  return {
    "GET /v1/auth/me": me,
    "GET /v1/kb/entries": entriesResponse(ENTRIES),
    "GET /v1/kb/publishes": { items: [] },
    "GET /v1/departments": DEPARTMENTS,
    ...extra,
  };
}

function record(partial: Partial<KBPublishRecord>): KBPublishRecord {
  return { id: 1, kb_version: "v1", at: "2026-10-31T10:00:00+00:00", mode: "mock", actor: "admin@demo", ...partial };
}

describe("L8: publish mode comes from the history, not the warning text", () => {
  async function publish() {
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Publish KB" }));
    await user.click(screen.getByRole("button", { name: "Confirm publish" }));
  }

  it("newestPublishMode picks the newest row's mode", () => {
    expect(newestPublishMode([record({ id: 1, mode: "mock" }), record({ id: 2, at: "2026-10-31T11:00:00+00:00", mode: "live" })])).toBe("live");
    expect(newestPublishMode([record({ id: 3, at: "2026-10-31T12:00:00+00:00", mode: "mock" }), record({ id: 2, mode: "live" })])).toBe("mock");
    expect(newestPublishMode([record({ mode: "weird" })])).toBeNull();
    expect(newestPublishMode([])).toBeNull();
    expect(newestPublishMode(undefined)).toBeNull();
  });

  it("refetches the history right after publishing and shows MOCK from the history row even without warning text", async () => {
    let published = false;
    const fetchMock = mockFetch(
      routes(ADMIN_ME, {
        "GET /v1/kb/publishes": () => ({ items: published ? [record({ id: 7, mode: "mock" })] : [] }),
        "POST /v1/kb/publish": () => {
          published = true;
          return versionInfo({ warnings: [] }); // no "mock publish" text at all
        },
      }),
    );
    renderWithAuth(<KbPage />);
    await publish();
    const result = await screen.findByTestId("publish-result");
    expect(within(result).getByTestId("mock-publish-banner")).toBeInTheDocument();
    expect(within(result).getByText("Publish (mock)")).toBeInTheDocument();
    const historyGets = fetchMock.mock.calls.filter((c) => String(c[0]).includes("/v1/kb/publishes"));
    expect(historyGets.length).toBeGreaterThanOrEqual(2); // initial load + the one right after the publish
  });

  it("shows LIVE from the history even if a warning happens to contain the words 'mock publish'", async () => {
    let published = false;
    mockFetch(
      routes(ADMIN_ME, {
        "GET /v1/kb/publishes": () => ({ items: published ? [record({ id: 8, mode: "live" })] : [] }),
        "POST /v1/kb/publish": () => {
          published = true;
          return versionInfo({ warnings: ["note: an earlier mock publish was replaced"] });
        },
      }),
    );
    renderWithAuth(<KbPage />);
    await publish();
    const result = await screen.findByTestId("publish-result");
    expect(within(result).queryByTestId("mock-publish-banner")).not.toBeInTheDocument();
    expect(within(result).getByText("Publish (live)")).toBeInTheDocument();
  });

  it("falls back to the warning text only when the history is unavailable", async () => {
    let published = false;
    mockFetch(
      routes(ADMIN_ME, {
        "GET /v1/kb/publishes": () => (published ? errorResponse(500, "internal", "history down") : { items: [] }),
        "POST /v1/kb/publish": () => {
          published = true;
          return versionInfo({ warnings: ["mock publish: nothing was sent"] });
        },
      }),
    );
    renderWithAuth(<KbPage />);
    await publish();
    const result = await screen.findByTestId("publish-result");
    expect(within(result).getByTestId("mock-publish-banner")).toBeInTheDocument();
    expect(within(result).getByText("Publish (mock)")).toBeInTheDocument();
  });
});

describe("staff on the KB page", () => {
  it("hides the import button and panel for staff, shows it for admins", async () => {
    mockFetch(routes(STAFF_ME));
    const staff = renderWithAuth(<KbPage />);
    await screen.findByText("FEE-101");
    await waitFor(() => expect(screen.getByText(/Only admins can publish/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /Import JSONL/ })).not.toBeInTheDocument();
    staff.unmount();
    vi.unstubAllGlobals();
    mockFetch(routes(ADMIN_ME));
    renderWithAuth(<KbPage />);
    expect(await screen.findByRole("button", { name: /Import JSONL/ })).toBeInTheDocument();
  });

  it("explains a 409 when staff try to overwrite an approved entry", async () => {
    mockFetch(
      routes(STAFF_ME, {
        "POST /v1/kb/entries": errorResponse(409, "conflict", "KB entry FEE-101 is approved; only an admin can change it"),
      }),
    );
    renderWithAuth(<KbPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit FEE-101" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByTestId("approved-staff-note")).toHaveTextContent(/cannot overwrite an approved or archived entry/);
    await user.click(within(dialog).getByRole("button", { name: /Save as draft/ }));
    const conflict = await within(dialog).findByTestId("save-conflict");
    expect(conflict).toHaveTextContent(/staff cannot overwrite it/);
    expect(conflict.parentElement).toHaveTextContent(/only an admin can change it \(conflict, HTTP 409\)/);
  });

  it("explains a 403 on save", async () => {
    mockFetch(routes(STAFF_ME, { "POST /v1/kb/entries": errorResponse(403, "unauthorized", "Admin role required") }));
    renderWithAuth(<KbPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit FEE-102" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /Save as draft/ }));
    expect(await within(dialog).findByTestId("save-forbidden")).toHaveTextContent(/not allowed/);
  });
});

describe("L9: KB draft from a ticket resolution", () => {
  const seed = buildTicketDraftSeed(
    { ticket_id: "EX-1001", department: "exam_cell", summary: "Hall ticket not visible" },
    "Hall tickets are released 3 days before the exam.",
  );

  it("builds a seed and survives readDraftSeed; gap seeds stay backwards compatible", () => {
    expect(seed.sourceTitle).toBe("Resolved ticket EX-1001");
    expect(readDraftSeed({ [KB_DRAFT_STATE_KEY]: seed })).toEqual(seed);
    const gap = { source: "gap", clusterId: "gc-1", label: "Bus", department: "transport", questionVariants: ["a"], idPrefix: "TRA" };
    expect(readDraftSeed({ [KB_DRAFT_STATE_KEY]: gap })).toEqual(gap); // no answerEn / sourceTitle keys appear
    expect(valuesFromSeed(gap as never)).toMatchObject({ answerEn: "", sourceTitle: "", id: "TRA-" });
    expect(readDraftSeed({ [KB_DRAFT_STATE_KEY]: { source: "ticket", questionVariants: [] } })).toBeNull();
    expect(readDraftSeed(null)).toBeNull();
  });

  it("opens the editor with question, answer, department and source title prefilled", async () => {
    mockFetch(routes(STAFF_ME));
    renderWithAuth(
      <>
        <KbPage />
        <LocationProbe />
      </>,
      { route: "/kb", state: { [KB_DRAFT_STATE_KEY]: seed } },
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Prefilled from the resolution of ticket EX-1001/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^ID/)).toHaveValue("EC-");
    expect(screen.getByLabelText(/^Question variants/)).toHaveValue("Hall ticket not visible");
    expect(screen.getByLabelText(/^Answer \(English\)/)).toHaveValue("Hall tickets are released 3 days before the exam.");
    expect(screen.getByLabelText(/^Source title/)).toHaveValue("Resolved ticket EX-1001");
    await waitFor(() => expect(screen.getByLabelText(/^Department/)).toHaveValue("exam_cell"));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("null"));
  });
});

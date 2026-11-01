/** Test helpers for the KB page tests (not imported by production code). */
import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { AuthProvider } from "../../auth/AuthContext";
import type { KBEntry, DepartmentsConfig, KBVersionInfo } from "../../api/types";
import type { KBEntriesResponse, Me } from "../../api/extra";
import { testQueryClient } from "../../test/utils";

export const ADMIN_ME: Me = { email: "admin@demo", role: "admin", department: null };
export const STAFF_ME: Me = { email: "exam@demo", role: "staff", department: "exam_cell" };

export const DEPARTMENTS: DepartmentsConfig = {
  timezone: "Asia/Kolkata",
  default_department: "helpdesk",
  emergency: { public_numbers: ["112"] },
  departments: [
    {
      key: "exam_cell",
      name: "Examination Cell",
      ticket_prefix: "EX",
      transfer_numbers: ["+910000000101", "+910000000102"],
      sms_alert_numbers: ["+910000000101"],
      hours: [
        { days: ["mon", "tue", "wed", "thu", "fri"], open: "09:00", close: "17:00" },
        { days: ["sat"], open: "09:00", close: "13:00" },
      ],
      topics: ["exam", "admit card"],
      mvp: true,
    },
    {
      key: "accounts",
      name: "Accounts / Fees",
      ticket_prefix: "AC",
      transfer_numbers: ["+910000000201"],
      hours: [{ days: ["mon", "tue", "wed", "thu", "fri"], open: "09:30", close: "16:30" }],
      topics: ["fee", "refund"],
      mvp: true,
    },
    {
      key: "transport",
      name: "Transport",
      ticket_prefix: "TR",
      transfer_numbers: ["+910000000401"],
      hours: [],
      topics: [],
      mvp: false,
    },
  ],
};

export function kbEntry(partial: Partial<KBEntry> & Pick<KBEntry, "id">): KBEntry {
  return {
    department: "accounts",
    question_variants: [`Question for ${partial.id}`],
    answer_en: `Answer for ${partial.id}`,
    answer_hi: null,
    source_title: "Fee Notice 2026-27",
    source_ref: null,
    valid_from: null,
    valid_until: null,
    tags: [],
    is_faq: false,
    status: "draft",
    ...partial,
  };
}

export function entriesResponse(entries: KBEntry[], flagged: string[] = []): KBEntriesResponse {
  return {
    items: entries,
    flagged_ids: flagged,
    meta: Object.fromEntries(
      entries.map((e) => [e.id, { flagged: flagged.includes(e.id), updated_at: "2026-10-31T06:00:00+00:00", updated_by: "admin@demo" }]),
    ),
  };
}

export function versionInfo(partial: Partial<KBVersionInfo> = {}): KBVersionInfo {
  return {
    kb_version: "a1b2c3d4e5f6",
    entry_count: 12,
    faq_count: 6,
    token_count: 4210,
    activated_at: "2026-10-31T10:15:00+05:30",
    warnings: [],
    ...partial,
  };
}

/** Shows router location and state, to assert navigation. */
export function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location" data-pathname={location.pathname} data-search={location.search}>
      {JSON.stringify(location.state)}
    </div>
  );
}

export function renderWithAuth(
  ui: ReactElement,
  { route = "/kb", state }: { route?: string; state?: unknown } = {},
) {
  const client = testQueryClient();
  const entry = state === undefined ? route : { pathname: route.split("?")[0]!, search: route.includes("?") ? `?${route.split("?")[1]}` : "", state };
  const result = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, client };
}

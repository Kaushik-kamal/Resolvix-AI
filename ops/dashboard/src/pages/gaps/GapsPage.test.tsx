import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GapCluster } from "../../api/types";
import { errorResponse, mockFetch, renderWithProviders } from "../../test/utils";
import { LocationProbe } from "../kb/testUtils";
import GapsPage, { sortClusters } from "./GapsPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function cluster(partial: Partial<GapCluster> & Pick<GapCluster, "cluster_id" | "label">): GapCluster {
  return {
    department: "transport",
    count: 1,
    examples: [],
    last_seen: new Date(Date.now() - 5 * 60_000).toISOString(),
    status: "new",
    ...partial,
  };
}

const BUS = cluster({
  cluster_id: "gc-1",
  label: "Bus Noida",
  count: 9,
  examples: ["bus kab aayegi", "Noida bus timing", "bus pass kahan se milega"],
});
const WIFI = cluster({ cluster_id: "gc-2", label: "Hostel Wifi", department: "hostel", count: 4, examples: ["wifi nahi chal raha"] });
const FEE = cluster({ cluster_id: "gc-3", label: "Fee Refund", department: "accounts", count: 12, status: "needs_document", examples: ["refund kab milega"] });

function page() {
  return renderWithProviders(
    <Routes>
      <Route path="/gaps" element={<GapsPage />} />
      <Route path="/kb" element={<LocationProbe />} />
    </Routes>,
    { route: "/gaps" },
  );
}

function rowOf(id: string): HTMLElement {
  const row = document.querySelector(`tr[data-row-key="${id}"]`);
  if (!row) throw new Error(`row ${id} not found`);
  return row as HTMLElement;
}

describe("sortClusters", () => {
  it("orders by count desc, then last_seen desc, then id", () => {
    const a = cluster({ cluster_id: "gc-1", label: "a", count: 5, last_seen: "2026-10-30T10:00:00+00:00" });
    const b = cluster({ cluster_id: "gc-2", label: "b", count: 5, last_seen: "2026-10-31T10:00:00+00:00" });
    const c = cluster({ cluster_id: "gc-3", label: "c", count: 9, last_seen: "2026-10-01T10:00:00+00:00" });
    const d = cluster({ cluster_id: "gc-10", label: "d", count: 5, last_seen: "2026-10-31T10:00:00+00:00" });
    expect(sortClusters([a, b, c, d]).map((x) => x.cluster_id)).toEqual(["gc-3", "gc-2", "gc-10", "gc-1"]);
  });
});

describe("Gaps page", () => {
  it("shows clusters sorted by count with label, department, examples, last seen and status", async () => {
    mockFetch({ "GET /v1/gaps/clusters": { items: [WIFI, BUS, FEE] } });
    page();
    await screen.findByText("Bus Noida");
    const order = Array.from(document.querySelectorAll("tbody tr")).map((r) => r.getAttribute("data-row-key"));
    expect(order).toEqual(["gc-3", "gc-1", "gc-2"]);

    const bus = within(rowOf("gc-1"));
    expect(bus.getByText("Transport")).toBeInTheDocument();
    expect(bus.getByText("9")).toBeInTheDocument();
    expect(bus.getByText("bus kab aayegi")).toBeInTheDocument();
    expect(bus.getByText("bus pass kahan se milega")).toBeInTheDocument();
    expect(bus.getByText("5m ago")).toBeInTheDocument();
    expect(bus.getByText("New")).toBeInTheDocument();
    expect(within(rowOf("gc-3")).getByText("Needs document", { selector: "span[data-status]" })).toBeInTheDocument();
  });

  it("only shows the last five examples", async () => {
    const many = cluster({ cluster_id: "gc-9", label: "Many", examples: ["e1", "e2", "e3", "e4", "e5", "e6", "e7"] });
    mockFetch({ "GET /v1/gaps/clusters": { items: [many] } });
    page();
    await screen.findByText("Many");
    expect(screen.queryByText("e2")).not.toBeInTheDocument();
    expect(screen.getByText("e3")).toBeInTheDocument();
    expect(screen.getByText("e7")).toBeInTheDocument();
  });

  it("PATCHes the status and refreshes the list", async () => {
    let status: GapCluster["status"] = "new";
    const fetchMock = mockFetch({
      "GET /v1/gaps/clusters": () => ({ items: [{ ...BUS, status }] }),
      "PATCH /v1/gaps/clusters/gc-1": (_url: URL, init: RequestInit) => {
        status = JSON.parse(String(init.body)).status;
        return { ...BUS, status };
      },
    });
    page();
    await screen.findByText("Bus Noida");
    const user = userEvent.setup();
    await user.click(within(rowOf("gc-1")).getByRole("button", { name: "Needs document" }));

    await waitFor(() => expect(within(rowOf("gc-1")).getByText("Needs document", { selector: "span[data-status]" })).toBeInTheDocument());
    const patch = fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === "PATCH");
    expect(String(patch![0])).toContain("/v1/gaps/clusters/gc-1");
    expect(JSON.parse(String((patch![1] as RequestInit).body))).toEqual({ status: "needs_document" });
    // refetched after the mutation
    await waitFor(() => expect(fetchMock.mock.calls.filter((c) => (c[1] as RequestInit)?.method !== "PATCH").length).toBeGreaterThanOrEqual(2));
    // the active status button is disabled and offers a reset
    expect(within(rowOf("gc-1")).getByRole("button", { name: "Needs document" })).toBeDisabled();
    await user.click(within(rowOf("gc-1")).getByRole("button", { name: "Reset to new" }));
    await waitFor(() => expect(within(rowOf("gc-1")).queryByRole("button", { name: "Reset to new" })).not.toBeInTheDocument());
  });

  it("offers answered and ignored too", async () => {
    let status: GapCluster["status"] = "new";
    mockFetch({
      "GET /v1/gaps/clusters": () => ({ items: [{ ...BUS, status }] }),
      "PATCH /v1/gaps/clusters/gc-1": (_u: URL, init: RequestInit) => {
        status = JSON.parse(String(init.body)).status;
        return { ...BUS, status };
      },
    });
    page();
    await screen.findByText("Bus Noida");
    const user = userEvent.setup();
    expect(within(rowOf("gc-1")).getByRole("button", { name: "Answered" })).toBeInTheDocument();
    await user.click(within(rowOf("gc-1")).getByRole("button", { name: "Ignored" }));
    await waitFor(() => expect(within(rowOf("gc-1")).getByText("Ignored", { selector: "span[data-status]" })).toBeInTheDocument());
  });

  it("shows an error banner when the PATCH fails", async () => {
    mockFetch({
      "GET /v1/gaps/clusters": { items: [BUS] },
      "PATCH /v1/gaps/clusters/gc-1": errorResponse(500, "internal", "database is locked"),
    });
    page();
    await screen.findByText("Bus Noida");
    await userEvent.click(within(rowOf("gc-1")).getByRole("button", { name: "Answered" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Could not update/);
    expect(alert).toHaveTextContent(/database is locked/);
    expect(within(rowOf("gc-1")).getByText("New")).toBeInTheDocument();
  });

  it("Draft KB entry navigates to /kb with the prefill in router state", async () => {
    mockFetch({ "GET /v1/gaps/clusters": { items: [BUS] } });
    page();
    await screen.findByText("Bus Noida");
    await userEvent.click(within(rowOf("gc-1")).getByRole("button", { name: /Draft KB entry/ }));
    const probe = await screen.findByTestId("location");
    expect(probe).toHaveAttribute("data-pathname", "/kb");
    const state = JSON.parse(probe.textContent ?? "{}");
    expect(state.kbDraft).toMatchObject({
      source: "gap",
      clusterId: "gc-1",
      label: "Bus Noida",
      department: "transport",
      questionVariants: ["bus kab aayegi", "Noida bus timing", "bus pass kahan se milega"],
      idPrefix: "TRA",
    });
  });

  it("filters by status", async () => {
    mockFetch({ "GET /v1/gaps/clusters": { items: [BUS, FEE] } });
    page();
    await screen.findByText("Bus Noida");
    await userEvent.selectOptions(screen.getByLabelText("Filter clusters by status"), "needs_document");
    expect(screen.queryByText("Bus Noida")).not.toBeInTheDocument();
    expect(screen.getByText("Fee Refund")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Filter clusters by status"), "ignored");
    expect(await screen.findByText(/No clusters with status "Ignored"/)).toBeInTheDocument();
  });

  it("shows loading, empty and error states", async () => {
    mockFetch({ "GET /v1/gaps/clusters": { items: [] } });
    const first = page();
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(await screen.findByText("No knowledge gaps yet")).toBeInTheDocument();
    first.unmount();

    mockFetch({ "GET /v1/gaps/clusters": errorResponse(500, "internal", "boom") });
    page();
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
  });
});

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import {
  DataTable,
  Drawer,
  EmptyState,
  ErrorState,
  LoadingState,
  MaskedNumber,
  ModeBadge,
  PriorityBadge,
  RelativeTime,
  StatusChip,
  type Column,
} from "./index";

const MASKED = "+91•••••0002";

describe("PriorityBadge", () => {
  it("renders the priority with its colour class and an accessible name", () => {
    render(<PriorityBadge priority="P1" />);
    const badge = screen.getByLabelText("Priority P1");
    expect(badge).toHaveTextContent("P1");
    expect(badge).toHaveClass("bg-p1");
    expect(badge).toHaveAttribute("data-priority", "P1");
  });
  it("falls back to a neutral badge for unknown values", () => {
    render(<PriorityBadge priority={null} />);
    expect(screen.getByLabelText("Priority unknown")).toHaveTextContent("?");
  });
});

describe("StatusChip / ModeBadge", () => {
  it("humanizes the status and keeps the raw value as data-status", () => {
    render(<StatusChip status="in_progress" />);
    expect(screen.getByText("In progress")).toHaveAttribute("data-status", "in_progress");
  });
  it("shows SMS (mock) vs SMS (live) and nothing without a mode", () => {
    const { rerender, container } = render(<ModeBadge mode="mock" />);
    expect(screen.getByText("SMS (mock)")).toHaveAttribute("data-mode", "mock");
    rerender(<ModeBadge mode="live" />);
    expect(screen.getByText("SMS (live)")).toBeInTheDocument();
    rerender(<ModeBadge mode={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("MaskedNumber", () => {
  it("shows the masked value and never an unmasked one", () => {
    render(<MaskedNumber value="+919876540002" />);
    expect(screen.getByTestId("masked-number")).toHaveTextContent(MASKED);
    expect(screen.queryByText("+919876540002")).not.toBeInTheDocument();
  });
  it("renders a dash for missing values", () => {
    render(<MaskedNumber value={null} />);
    expect(screen.getByTestId("masked-number")).toHaveTextContent("—");
  });
  it("offers a reveal button only when a handler is given and calls it", async () => {
    const onToggle = vi.fn();
    const { rerender } = render(<MaskedNumber value={MASKED} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    rerender(<MaskedNumber value={MASKED} onToggleReveal={onToggle} />);
    await userEvent.click(screen.getByRole("button", { name: /reveal number/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(<MaskedNumber value="+919876540002" revealed onToggleReveal={onToggle} />);
    expect(screen.getByTestId("masked-number")).toHaveTextContent("+919876540002");
  });
});

describe("states", () => {
  it("LoadingState, EmptyState and ErrorState render their roles", async () => {
    const onRetry = vi.fn();
    render(
      <>
        <LoadingState label="Fetching" />
        <EmptyState title="Nothing" hint="Try later" />
        <ErrorState error={new ApiError({ code: "upstream_error", message: "Runtime down", status: 502 })} onRetry={onRetry} />
      </>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Fetching");
    expect(screen.getByText("Try later")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Runtime down (upstream_error, HTTP 502)");
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe("RelativeTime", () => {
  it("renders a time element with the IST absolute time as title", () => {
    render(<RelativeTime value="2026-10-31T10:15:00+00:00" />);
    const el = screen.getByRole("time");
    expect(el).toHaveAttribute("title", "31 Oct 2026, 15:45 IST");
    expect(el).toHaveAttribute("dateTime", "2026-10-31T10:15:00.000Z");
  });
  it("shows a dash for missing values", () => {
    render(<RelativeTime value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

interface Row {
  id: string;
  name: string;
  count: number;
}
const columns: Column<Row>[] = [
  { key: "name", header: "Name", cell: (r) => r.name, sortValue: (r) => r.name },
  { key: "count", header: "Count", cell: (r) => r.count, sortValue: (r) => r.count, align: "right" },
];
const rows: Row[] = [
  { id: "a", name: "bravo", count: 5 },
  { id: "b", name: "alpha", count: 20 },
  { id: "c", name: "charlie", count: 1 },
];

describe("DataTable", () => {
  it("renders rows, sorts on header click and reports row clicks", async () => {
    const onRowClick = vi.fn();
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} onRowClick={onRowClick} />);
    const names = () => screen.getAllByRole("row").slice(1).map((tr) => within(tr).getAllByRole("cell")[0].textContent);
    expect(names()).toEqual(["bravo", "alpha", "charlie"]);

    await userEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(names()).toEqual(["alpha", "bravo", "charlie"]);
    await userEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(names()).toEqual(["charlie", "bravo", "alpha"]);
    await userEvent.click(screen.getByRole("button", { name: "Count" }));
    expect(names()).toEqual(["charlie", "bravo", "alpha"]); // 1, 5, 20 ascending

    await userEvent.click(screen.getByText("alpha"));
    expect(onRowClick).toHaveBeenCalledWith(rows[1]);
  });
  it("activates a row with the keyboard", async () => {
    const onRowClick = vi.fn();
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} onRowClick={onRowClick} />);
    screen.getAllByRole("row")[1].focus();
    await userEvent.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
  });
  it("shows loading, error and empty states", () => {
    const { rerender } = render(<DataTable columns={columns} rows={undefined} rowKey={(r) => r.id} isLoading />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    rerender(<DataTable columns={columns} rows={undefined} rowKey={(r) => r.id} error={new Error("boom")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    rerender(<DataTable columns={columns} rows={[]} rowKey={(r) => r.id} emptyTitle="No rows" />);
    expect(screen.getByText("No rows")).toBeInTheDocument();
  });
  it("keeps showing rows during a background refetch", () => {
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} isLoading />);
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });
});

describe("Drawer", () => {
  function Harness() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>open it</button>
        <Drawer open={open} onClose={() => setOpen(false)} title="EX-1001" subtitle="Exam cell" footer={<span>footer</span>}>
          <input aria-label="note" />
        </Drawer>
      </>
    );
  }
  it("opens, keeps focus on typing, closes on Escape and returns focus", async () => {
    render(<Harness />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const trigger = screen.getByText("open it");
    await userEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "EX-1001" });
    expect(dialog).toHaveFocus();
    await userEvent.click(screen.getByLabelText("note"));
    await userEvent.keyboard("hello"); // typing re-renders nothing in the harness, focus must stay
    expect(screen.getByLabelText("note")).toHaveValue("hello");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
  it("closes on backdrop click and the close button", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByText("open it"));
    await userEvent.click(screen.getByTestId("drawer-backdrop"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("open it"));
    await userEvent.click(screen.getByRole("button", { name: "Close panel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

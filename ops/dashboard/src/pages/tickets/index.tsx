import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Search, X } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, qk, type ListTicketsParams, type TicketRow } from "../../api";
import { useAlerts } from "../../alerts/AlertContext";
import {
  Button,
  DataTable,
  PageHeader,
  Panel,
  PriorityBadge,
  RelativeTime,
  StatusChip,
  type Column,
} from "../../components";
import { humanize } from "../../lib/format";
import { filterTickets, TICKET_PRIORITIES, TICKET_STATUSES, type TicketFilters } from "./ticketLogic";
import { TicketDrawer } from "./TicketDrawer";

const LIST_LIMIT = 500;

/** Tickets table with filters + search; `?ticket=<id>` opens the detail drawer (closing removes the parameter). */
export default function TicketsPage() {
  const [params, setParams] = useSearchParams();
  const { isFlashing } = useAlerts();
  const [query, setQuery] = useState("");

  const status = params.get("status") ?? "";
  const department = params.get("department") ?? "";
  const priority = params.get("priority") ?? "";
  const openTicket = params.get("ticket");
  const filters: TicketFilters = { status, department, priority, query };

  const setParam = useCallback(
    (key: string, value: string) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) next.set(key, value);
          else next.delete(key);
          return next;
        },
        // opening a drawer is a history entry (Back closes it); closing and filter changes replace the entry
        { replace: key !== "ticket" || value === "" },
      );
    },
    [setParams],
  );

  const listParams: ListTicketsParams = {
    ...(status ? { status } : {}),
    ...(department ? { department } : {}),
    ...(priority ? { priority } : {}),
    limit: LIST_LIMIT,
  };
  const list = useQuery({
    queryKey: qk.tickets.list(listParams),
    queryFn: ({ signal }) => api.listTickets(listParams, signal),
  });
  const departments = useQuery({
    queryKey: qk.config.departments,
    queryFn: ({ signal }) => api.getDepartments(signal),
    staleTime: Infinity,
  });

  const rows = useMemo(() => (list.data ? filterTickets(list.data.items, filters) : undefined), [list.data, status, department, priority, query]); // eslint-disable-line react-hooks/exhaustive-deps
  const knownAssignees = useMemo(
    () => Array.from(new Set((list.data?.items ?? []).map((t) => t.assignee).filter((a): a is string => Boolean(a)))).sort(),
    [list.data],
  );

  const departmentOptions = useMemo(() => {
    const fromConfig = departments.data?.departments.map((d) => ({ key: d.key, name: d.name })) ?? [];
    const known = new Set(fromConfig.map((d) => d.key));
    const extra = (list.data?.items ?? [])
      .map((t) => t.department)
      .filter((key) => !known.has(key))
      .map((key) => ({ key, name: humanize(key) }));
    const merged = [...fromConfig, ...extra];
    return merged.filter((d, i) => merged.findIndex((o) => o.key === d.key) === i);
  }, [departments.data, list.data]);

  const departmentNames = useMemo(() => new Map(departmentOptions.map((d) => [d.key, d.name])), [departmentOptions]);

  const anyFilter = Boolean(status || department || priority || query.trim());
  const clearFilters = () => {
    setQuery("");
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        ["status", "department", "priority"].forEach((key) => next.delete(key));
        return next;
      },
      { replace: true },
    );
  };

  const columns: Column<TicketRow>[] = [
    { key: "priority", header: "Pri", width: "4.5rem", cell: (t) => <PriorityBadge priority={t.priority} /> },
    {
      key: "id",
      header: "Ticket",
      width: "7rem",
      cell: (t) => <span className="font-mono text-xs font-semibold">{t.ticket_id}</span>,
    },
    {
      key: "summary",
      header: "Summary",
      cell: (t) => <span className="line-clamp-2 max-w-[34rem] text-[13px] leading-snug">{t.summary}</span>,
    },
    { key: "department", header: "Department", cell: (t) => departmentNames.get(t.department) ?? humanize(t.department) },
    { key: "status", header: "Status", cell: (t) => <StatusChip status={t.status} /> },
    {
      key: "assignee",
      header: "Assignee",
      cell: (t) => (t.assignee ? <span className="text-xs">{t.assignee}</span> : <span className="text-xs text-ink-faint">Unassigned</span>),
    },
    {
      key: "caller",
      header: "Caller",
      cell: (t) => <span className="font-mono text-xs">{t.caller_number ?? "—"}</span>,
    },
    {
      key: "created",
      header: "Created",
      width: "6rem",
      cell: (t) => <RelativeTime value={t.created_at} className="text-xs text-ink-soft" />,
    },
  ];

  const total = list.data?.items.length ?? 0;

  return (
    <>
      <PageHeader
        title="Tickets"
        subtitle="P1 first, then newest first. Updates arrive live."
        actions={
          <Button size="sm" onClick={() => void list.refetch()} disabled={list.isFetching} aria-label="Refresh tickets">
            <RefreshCw size={14} className={list.isFetching ? "animate-spin" : undefined} aria-hidden /> Refresh
          </Button>
        }
      />
      <Panel flush>
        <form
          role="search"
          aria-label="Ticket filters"
          className="flex flex-wrap items-end gap-3 border-b border-line px-4 py-3"
          onSubmit={(event) => event.preventDefault()}
        >
          <div className="min-w-[14rem] flex-1">
            <label className="label" htmlFor="ticket-search">
              Search
            </label>
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint" aria-hidden />
              <input
                id="ticket-search"
                type="search"
                className="input pl-8"
                placeholder="Ticket id or words in the summary"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="ticket-status">
              Status
            </label>
            <select id="ticket-status" className="input" value={status} onChange={(e) => setParam("status", e.target.value)}>
              <option value="">All statuses</option>
              {TICKET_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="ticket-department">
              Department
            </label>
            <select id="ticket-department" className="input" value={department} onChange={(e) => setParam("department", e.target.value)}>
              <option value="">All departments</option>
              {departmentOptions.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="ticket-priority">
              Priority
            </label>
            <select id="ticket-priority" className="input" value={priority} onChange={(e) => setParam("priority", e.target.value)}>
              <option value="">All priorities</option>
              {TICKET_PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          {anyFilter ? (
            <Button size="sm" variant="ghost" onClick={clearFilters}>
              <X size={14} aria-hidden /> Clear filters
            </Button>
          ) : null}
          <p className="ml-auto self-center text-xs text-ink-soft" aria-live="polite">
            {rows ? `${rows.length} of ${total} tickets` : ""}
          </p>
        </form>
        <DataTable
          caption="Tickets"
          columns={columns}
          rows={rows}
          rowKey={(t) => t.ticket_id}
          onRowClick={(t) => setParam("ticket", t.ticket_id)}
          selectedKey={openTicket}
          isLoading={list.isPending}
          error={list.error}
          onRetry={() => void list.refetch()}
          emptyTitle={anyFilter ? "No tickets match these filters" : "No tickets yet"}
          emptyHint={anyFilter ? "Try a different search or clear the filters." : "New tickets from calls appear here as they are created."}
          emptyAction={
            anyFilter ? (
              <Button size="sm" onClick={clearFilters}>
                Clear filters
              </Button>
            ) : undefined
          }
          rowClassName={(t) => (isFlashing(t.ticket_id) ? "animate-flash" : undefined)}
        />
      </Panel>
      {openTicket ? (
        <TicketDrawer
          key={openTicket}
          ticketId={openTicket}
          knownAssignees={knownAssignees}
          onClose={() => setParam("ticket", "")}
        />
      ) : null}
    </>
  );
}

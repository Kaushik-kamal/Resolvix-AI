import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useMemo, type ReactNode } from "react";
import { api, qk } from "../../api";
import type { Department, DepartmentsConfig } from "../../api/types";
import { DataTable, MaskedNumber, PageHeader, Panel, PriorityBadge, type Column } from "../../components";
import { humanize, ticketTypeLabel } from "../../lib/format";
import {
  describeValue,
  formatHours,
  isShortPublicNumber,
  rulesDocView,
  type RuleView,
} from "./rulesModel";

function Chip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center whitespace-nowrap rounded border border-line bg-bg px-1.5 py-0.5 text-xs text-ink-soft",
        className,
      )}
    >
      {children}
    </span>
  );
}

/**
 * A number list: private numbers go through MaskedNumber (no reveal button: this page is display only). Non-admin
 * sessions get already-masked numbers from the API ("+91•••••0101"); MaskedNumber leaves those unchanged instead of
 * masking them a second time. Emergency numbers such as 112 are public and stay plain text. The index is part of the
 * key because two different masked numbers can look identical.
 */
function NumberList({ numbers }: { numbers: readonly string[] | undefined }) {
  if (!numbers || numbers.length === 0) return <span className="text-ink-faint">None</span>;
  return (
    <ul className="space-y-0.5">
      {numbers.map((n, index) => (
        <li key={`${index}-${n}`}>{isShortPublicNumber(n) ? <span className="font-mono">{n}</span> : <MaskedNumber value={n} />}</li>
      ))}
    </ul>
  );
}

/** Renders any JSON value (lexicons, future config sections) as labelled chips without knowing its shape. */
function ValueBlock({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (value.every((v) => v === null || typeof v !== "object")) {
      return (
        <div className="flex flex-wrap gap-1">
          {value.map((v, i) => (
            <Chip key={`${i}-${describeValue(v)}`}>{describeValue(v)}</Chip>
          ))}
        </div>
      );
    }
    return <pre className="overflow-x-auto rounded bg-bg p-2 text-xs">{JSON.stringify(value, null, 2)}</pre>;
  }
  if (value && typeof value === "object") {
    return (
      <dl className="space-y-2">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs font-semibold uppercase tracking-wide text-ink-soft">{humanize(k)}</dt>
            <dd className="mt-0.5">
              <ValueBlock value={v} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span className="text-sm">{describeValue(value)}</span>;
}

// ---------------------------------------------------------------- urgency rules
function UrgencyRulesSection() {
  const query = useQuery({
    queryKey: qk.config.urgencyRules,
    queryFn: ({ signal }) => api.getUrgencyRules(signal),
    staleTime: Infinity,
  });
  const view = useMemo(() => (query.data ? rulesDocView(query.data) : undefined), [query.data]);
  const showExtras = !!view?.rules.some((r) => r.extras.length > 0);

  const columns: Column<RuleView>[] = [
    {
      key: "position",
      header: "#",
      width: "2.5rem",
      cell: (r) => <span className="tabular-nums text-ink-faint">{r.position}</span>,
    },
    { key: "id", header: "Rule", cell: (r) => <span className="font-mono text-xs font-semibold">{r.id}</span> },
    {
      key: "priority",
      header: "Priority",
      width: "5.5rem",
      cell: (r) =>
        r.priority ? (
          <PriorityBadge priority={r.priority} />
        ) : r.rawPriority ? (
          <Chip>{r.rawPriority}</Chip>
        ) : (
          <PriorityBadge priority={null} />
        ),
    },
    {
      key: "conditions",
      header: "Conditions (all must match)",
      cell: (r) =>
        r.conditions.length === 0 ? (
          <span className="text-xs italic text-ink-faint">Always (matches anything not caught above)</span>
        ) : (
          <ul className="flex flex-wrap gap-1">
            {r.conditions.map((c) => (
              <li key={`${c.field}-${c.op}`}>
                <Chip>
                  <span className="font-medium text-ink">{c.field}</span>
                  &nbsp;{c.op}&nbsp;{c.value}
                </Chip>
              </li>
            ))}
          </ul>
        ),
    },
    { key: "ticket_type", header: "Ticket type", cell: (r) => (r.ticketType ? ticketTypeLabel(r.ticketType) : null) ?? <span className="text-ink-faint">None</span> },
    {
      key: "department",
      header: "Department",
      cell: (r) =>
        r.department ? (
          <span className="font-mono text-xs">{r.department}</span>
        ) : (
          <span className="text-ink-faint">None</span>
        ),
    },
    { key: "action", header: "Action", cell: (r) => <span className="font-mono text-xs">{r.action ?? "—"}</span> },
    { key: "reason", header: "Reason", cell: (r) => <span className="text-xs">{r.reason ?? "—"}</span> },
    ...(showExtras
      ? [
          {
            key: "extras",
            header: "Other fields",
            cell: (r: RuleView) =>
              r.extras.length === 0 ? (
                <span className="text-ink-faint">—</span>
              ) : (
                <ul className="space-y-0.5 text-xs">
                  {r.extras.map(([k, v]) => (
                    <li key={k} className="break-words">
                      <span className="font-medium">{k}</span>: {v}
                    </li>
                  ))}
                </ul>
              ),
          } satisfies Column<RuleView>,
        ]
      : []),
  ];

  return (
    <div className="space-y-4">
      <Panel
        title={view?.version ? `Urgency rules (version ${view.version})` : "Urgency rules"}
        flush
        actions={<span className="text-xs text-ink-soft">Read only. Owned by the brain team; first matching rule wins.</span>}
      >
        {view?.malformed ? (
          <p role="alert" className="border-b border-line bg-[#F5E9D8] px-4 py-2 text-xs text-[#80551F]">
            The rules document has no list called &ldquo;rules&rdquo;; showing what could be read.
          </p>
        ) : null}
        <DataTable
          caption="Urgency rules in evaluation order"
          columns={columns}
          rows={view?.rules}
          rowKey={(r) => `${r.position}-${r.id}`}
          isLoading={query.isPending}
          error={query.error}
          onRetry={() => void query.refetch()}
          emptyTitle="No urgency rules"
          emptyHint="The API returned an empty rule list."
        />
      </Panel>

      {view && view.extras.length > 0 ? (
        <Panel title="Other settings in the rules file">
          <div className="space-y-2">
            {view.extras.map(([key, value]) => (
              <details key={key} className="rounded-md border border-line px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium">{humanize(key)}</summary>
                <div className="mt-2">
                  <ValueBlock value={value} />
                </div>
              </details>
            ))}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- departments
function DepartmentSummary({ config }: { config: DepartmentsConfig }) {
  const emergency = Object.entries(config.emergency ?? {});
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-2 border-b border-line px-4 py-3 text-sm">
      <div>
        <dt className="text-xs uppercase tracking-wide text-ink-soft">Default department</dt>
        <dd className="font-mono text-xs">{config.default_department}</dd>
      </div>
      {config.timezone ? (
        <div>
          <dt className="text-xs uppercase tracking-wide text-ink-soft">Time zone</dt>
          <dd>{config.timezone}</dd>
        </div>
      ) : null}
      {emergency.map(([group, numbers]) => (
        <div key={group}>
          <dt className="text-xs uppercase tracking-wide text-ink-soft">Emergency: {humanize(group).toLowerCase()}</dt>
          <dd>
            <NumberList numbers={numbers} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function DepartmentsSection() {
  const query = useQuery({
    queryKey: qk.config.departments,
    queryFn: ({ signal }) => api.getDepartments(signal),
    staleTime: Infinity,
  });

  const columns: Column<Department>[] = [
    {
      key: "name",
      header: "Department",
      cell: (d) => (
        <div>
          <div className="font-medium text-ink">{d.name}</div>
          <div className="font-mono text-[11px] text-ink-faint">{d.key}</div>
          {d.mvp === false ? <div className="text-[11px] text-ink-faint">Data only (not in the MVP)</div> : null}
        </div>
      ),
    },
    { key: "prefix", header: "Ticket prefix", width: "6rem", cell: (d) => <span className="font-mono text-xs">{d.ticket_prefix}</span> },
    {
      key: "hours",
      header: "Hours (IST)",
      cell: (d) =>
        d.hours && d.hours.length > 0 ? (
          <ul className="space-y-0.5 text-xs">
            {formatHours(d.hours).map((line) => (
              <li key={line} className="whitespace-nowrap">
                {line}
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-ink-faint">Not set</span>
        ),
    },
    { key: "transfer", header: "Transfer numbers", cell: (d) => <NumberList numbers={d.transfer_numbers} /> },
    { key: "alerts", header: "SMS alert numbers", cell: (d) => <NumberList numbers={d.sms_alert_numbers} /> },
    {
      key: "topics",
      header: "Topics",
      cell: (d) =>
        d.topics && d.topics.length > 0 ? (
          <div className="flex max-w-[22rem] flex-wrap gap-1">
            {d.topics.map((t) => (
              <Chip key={t}>{t}</Chip>
            ))}
          </div>
        ) : (
          <span className="text-ink-faint">None</span>
        ),
    },
  ];

  return (
    <Panel title="Departments" flush actions={<span className="text-xs text-ink-soft">Read only. Numbers are masked.</span>}>
      {query.data ? <DepartmentSummary config={query.data} /> : null}
      <DataTable
        caption="Departments"
        columns={columns}
        rows={query.data?.departments}
        rowKey={(d) => d.key}
        isLoading={query.isPending}
        error={query.error}
        onRetry={() => void query.refetch()}
        emptyTitle="No departments"
        emptyHint="The API returned an empty department list."
      />
    </Panel>
  );
}

export default function RulesPage() {
  return (
    <>
      <PageHeader
        title="Rules and departments"
        subtitle="Reference only. Priorities are decided by the rules below; they cannot be changed here."
      />
      <div className="space-y-4">
        <UrgencyRulesSection />
        <DepartmentsSection />
      </div>
    </>
  );
}

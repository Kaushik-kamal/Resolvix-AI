import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, qk } from "../../api";
import type { GapCluster, GapStatus } from "../../api";
import {
  Button,
  DataTable,
  PageHeader,
  Panel,
  RelativeTime,
  StatusChip,
  errorMessage,
  type Column,
} from "../../components";
import { formatCount, humanize, parseApiDate } from "../../lib/format";
import { KB_DRAFT_STATE_KEY, buildDraftSeed } from "../kb/draftSeed";

export const GAP_STATUSES: readonly GapStatus[] = ["new", "needs_document", "answered", "ignored"];

/** Buttons shown on every cluster: the three triage outcomes; "Reset to new" appears once a cluster left "new". */
const TRIAGE_ACTIONS: { status: GapStatus; label: string }[] = [
  { status: "needs_document", label: "Needs document" },
  { status: "answered", label: "Answered" },
  { status: "ignored", label: "Ignored" },
];

/** Same order as the API (count desc, last_seen desc, cluster_id); applied again so a stale cache can never reorder. */
export function sortClusters(items: readonly GapCluster[]): GapCluster[] {
  return [...items].sort((a, b) => {
    if (b.count !== a.count) return b.count - a.count;
    const ta = parseApiDate(a.last_seen)?.getTime() ?? 0;
    const tb = parseApiDate(b.last_seen)?.getTime() ?? 0;
    if (tb !== ta) return tb - ta;
    return a.cluster_id.localeCompare(b.cluster_id, undefined, { numeric: true });
  });
}

export default function GapsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"all" | GapStatus>("all");
  const [failure, setFailure] = useState<{ cluster: string; message: string } | null>(null);

  const query = useQuery({
    queryKey: qk.gaps.clusters,
    queryFn: ({ signal }) => api.listGapClusters(signal),
  });

  const patch = useMutation({
    mutationFn: (vars: { cluster: GapCluster; status: GapStatus }) =>
      api.patchGapCluster(vars.cluster.cluster_id, vars.status),
    onMutate: () => setFailure(null),
    onSuccess: (updated) => {
      queryClient.setQueryData<{ items: GapCluster[] }>(qk.gaps.clusters, (old) =>
        old ? { ...old, items: old.items.map((c) => (c.cluster_id === updated.cluster_id ? updated : c)) } : old,
      );
    },
    onError: (error, vars) => setFailure({ cluster: vars.cluster.label, message: errorMessage(error) }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: qk.gaps.all }),
  });

  const all = useMemo(() => (query.data ? sortClusters(query.data.items) : undefined), [query.data]);
  const rows = useMemo(() => (all && filter !== "all" ? all.filter((c) => c.status === filter) : all), [all, filter]);
  const pendingId = patch.isPending ? patch.variables?.cluster.cluster_id : undefined;

  const draftEntry = (cluster: GapCluster) =>
    navigate("/kb", { state: { [KB_DRAFT_STATE_KEY]: buildDraftSeed(cluster) } });

  const columns: Column<GapCluster>[] = [
    {
      key: "label",
      header: "Cluster",
      width: "13rem",
      cell: (c) => (
        <div>
          <div className="font-medium text-ink">{c.label}</div>
          <div className="font-mono text-[11px] text-ink-faint">{c.cluster_id}</div>
        </div>
      ),
    },
    {
      key: "department",
      header: "Department",
      width: "8rem",
      cell: (c) => (c.department ? humanize(c.department) : <span className="text-ink-faint">Unknown</span>),
    },
    {
      key: "count",
      header: "Count",
      align: "right",
      width: "5rem",
      cell: (c) => <span className="font-semibold tabular-nums">{formatCount(c.count)}</span>,
    },
    {
      key: "examples",
      header: "Examples (last 5)",
      cell: (c) =>
        c.examples.length === 0 ? (
          <span className="text-ink-faint">No examples</span>
        ) : (
          <ul className="space-y-0.5 text-xs text-ink-soft">
            {c.examples.slice(-5).map((example, i) => (
              <li key={`${i}-${example}`} className="line-clamp-2 break-words">
                {example}
              </li>
            ))}
          </ul>
        ),
    },
    {
      key: "last_seen",
      header: "Last seen",
      width: "6.5rem",
      cell: (c) => <RelativeTime value={c.last_seen} className="whitespace-nowrap text-xs text-ink-soft" />,
    },
    { key: "status", header: "Status", width: "8.5rem", cell: (c) => <StatusChip status={c.status} /> },
    {
      key: "actions",
      header: "Actions",
      width: "15rem",
      cell: (c) => {
        const busy = pendingId === c.cluster_id;
        return (
          <div className="flex flex-wrap gap-1" role="group" aria-label={`Actions for ${c.label}`}>
            {TRIAGE_ACTIONS.map(({ status, label }) => (
              <Button
                key={status}
                size="sm"
                variant={c.status === status ? "primary" : "secondary"}
                aria-pressed={c.status === status}
                disabled={busy || c.status === status}
                onClick={() => patch.mutate({ cluster: c, status })}
              >
                {label}
              </Button>
            ))}
            {c.status !== "new" ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => patch.mutate({ cluster: c, status: "new" })}
              >
                Reset to new
              </Button>
            ) : null}
            <Button size="sm" variant="secondary" onClick={() => draftEntry(c)} className="w-full">
              <FilePlus2 size={12} aria-hidden /> Draft KB entry
            </Button>
          </div>
        );
      },
    },
  ];

  const open = all?.filter((c) => c.status === "new" || c.status === "needs_document").length ?? 0;

  return (
    <>
      <PageHeader
        title="Knowledge gaps"
        subtitle={
          all
            ? `${all.length} ${all.length === 1 ? "cluster" : "clusters"}, most asked first. ${open} still need attention (new or needs document).`
            : "Questions the assistant could not answer, grouped by topic."
        }
        actions={
          <>
            <label className="flex items-center gap-2 text-xs text-ink-soft">
              <span className="font-medium uppercase tracking-wide">Status</span>
              <select
                className="input w-auto"
                value={filter}
                onChange={(e) => setFilter(e.target.value as "all" | GapStatus)}
                aria-label="Filter clusters by status"
              >
                <option value="all">All</option>
                {GAP_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {humanize(s)}
                  </option>
                ))}
              </select>
            </label>
            <Button size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}>
              <RefreshCw size={12} className={query.isFetching ? "animate-spin" : undefined} aria-hidden /> Refresh
            </Button>
          </>
        }
      />

      {failure ? (
        <div
          role="alert"
          className="mb-3 flex items-start justify-between gap-3 rounded-md border border-[#EBC4B6] bg-[#F6E1D9] px-3 py-2 text-sm text-[#8D3C21]"
        >
          <span>
            Could not update &ldquo;{failure.cluster}&rdquo;: {failure.message}
          </span>
          <button type="button" className="text-xs underline" onClick={() => setFailure(null)}>
            Dismiss
          </button>
        </div>
      ) : null}

      <Panel flush>
        <DataTable
          caption="Knowledge gap clusters"
          columns={columns}
          rows={rows}
          rowKey={(c) => c.cluster_id}
          isLoading={query.isPending}
          error={query.error}
          onRetry={() => void query.refetch()}
          emptyTitle={filter === "all" ? "No knowledge gaps yet" : `No clusters with status "${humanize(filter)}"`}
          emptyHint={
            filter === "all"
              ? "When the assistant cannot answer a question it is recorded here and grouped with similar ones."
              : "Change the status filter to see the other clusters."
          }
        />
      </Panel>
    </>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api, isApiError, qk } from "../../api";
import type { ListKbEntriesParams } from "../../api";
import { useAuth } from "../../auth/AuthContext";
import { Button, PageHeader, Panel, errorMessage } from "../../components";
import { useNow } from "../../hooks/useNow";
import { humanize } from "../../lib/format";
import { buildDraftSeed, readDraftSeed, type KbDraftSeed } from "./draftSeed";
import { EntriesTable, type KbRow, type KbStatus } from "./EntriesTable";
import { EntryEditor, type EditorTarget } from "./EntryEditor";
import { ImportPanel } from "./ImportPanel";
import { emptyFormValues, valuesFromEntry, valuesFromSeed } from "./kbModel";
import { PublishHistory, PublishPanel } from "./PublishPanel";

type Filter = "all" | KbStatus;
const FILTERS: Filter[] = ["all", "draft", "approved", "archived"];

interface Notice {
  tone: "good" | "bad";
  text: string;
}

export function targetFromSeed(seed: KbDraftSeed, nonce: number): EditorTarget {
  if (seed.source === "ticket") {
    return {
      mode: "new",
      values: valuesFromSeed(seed),
      nonce,
      note: `Prefilled from the resolution of ticket ${seed.ticketId ?? seed.label}: the question is the ticket summary and the answer is the resolution text. Rewrite both as a general answer, remove names and phone numbers, then finish the id and save as draft.`,
    };
  }
  return {
    mode: "new",
    values: valuesFromSeed(seed),
    nonce,
    note: `Prefilled from gap cluster "${seed.label}" (${seed.clusterId}): department and question variants come from its examples. Add the answer and source, then save as draft.`,
  };
}

export default function KbPage() {
  const queryClient = useQueryClient();
  const { isAdmin } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const now = new Date(useNow(60_000));

  const [filter, setFilter] = useState<Filter>("all");
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const nonce = useRef(0);
  const nextNonce = () => ++nonce.current;

  // ---- data
  const params: ListKbEntriesParams = filter === "all" ? {} : { status: filter };
  const entries = useQuery({
    queryKey: qk.kb.entries(params),
    queryFn: ({ signal }) => api.listKbEntries(params, signal),
  });
  const publishes = useQuery({
    queryKey: qk.kb.publishes,
    queryFn: ({ signal }) => api.listKbPublishes(signal),
  });

  const rows: KbRow[] | undefined = useMemo(() => {
    if (!entries.data) return undefined;
    const flaggedIds = new Set(entries.data.flagged_ids ?? []);
    return entries.data.items.map((entry) => ({
      entry,
      flagged: flaggedIds.has(entry.id) || !!entries.data.meta?.[entry.id]?.flagged,
      updatedAt: entries.data.meta?.[entry.id]?.updated_at,
    }));
  }, [entries.data]);

  // ---- "Draft KB entry" from /gaps arrives as router state; read it once, then clear it so a reload does not reopen it
  useEffect(() => {
    const seed = readDraftSeed(location.state);
    if (!seed) return;
    setEditor(targetFromSeed(seed, nextNonce()));
    navigate({ pathname: location.pathname, search: location.search }, { replace: true, state: null });
  }, [location.state, location.pathname, location.search, navigate]);

  // ---- optional deep link /kb?draftFromGap=<cluster_id>
  const draftFromGap = searchParams.get("draftFromGap");
  const gapLookup = useQuery({
    queryKey: qk.gaps.clusters,
    queryFn: ({ signal }) => api.listGapClusters(signal),
    enabled: !!draftFromGap,
  });
  useEffect(() => {
    if (!draftFromGap || !gapLookup.data) return;
    const cluster = gapLookup.data.items.find((c) => c.cluster_id === draftFromGap);
    if (cluster) setEditor(targetFromSeed(buildDraftSeed(cluster), nextNonce()));
    else setNotice({ tone: "bad", text: `Gap cluster ${draftFromGap} was not found.` });
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("draftFromGap");
        return next;
      },
      { replace: true },
    );
  }, [draftFromGap, gapLookup.data, setSearchParams]);

  // ---- approve / archive / restore (admin)
  const setStatus = useMutation({
    mutationFn: (vars: { id: string; status: KbStatus }) => api.setKbEntryStatus(vars.id, vars.status),
    onMutate: () => setNotice(null),
    onSuccess: (_res, vars) =>
      setNotice({
        tone: "good",
        text: `${vars.id} is now ${humanize(vars.status).toLowerCase()}.${
          vars.status === "approved" ? " Publish the KB to send it to the voice assistant." : ""
        }`,
      }),
    onError: (error, vars) => {
      let text: string;
      if (isApiError(error) && error.status === 409) {
        text = `Cannot approve ${vars.id}: it was flagged by the injection scan. Edit its text, save it again (a clean save clears the flag), then approve. (${error.message})`;
      } else if (isApiError(error) && error.status === 403) {
        text = "Only admins can approve or archive entries.";
      } else {
        text = `Could not change ${vars.id} to ${vars.status}: ${errorMessage(error)}`;
      }
      setNotice({ tone: "bad", text });
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: qk.kb.entriesAny }),
  });
  const busyId = setStatus.isPending ? setStatus.variables?.id : null;

  const openNew = useCallback(() => setEditor({ mode: "new", values: emptyFormValues(), nonce: nextNonce() }), []);
  const openEdit = useCallback(
    (row: KbRow) =>
      setEditor({
        mode: "edit",
        values: valuesFromEntry(row.entry),
        currentStatus: row.entry.status ?? "approved",
        flagged: row.flagged,
        nonce: nextNonce(),
      }),
    [],
  );

  const total = rows?.length;
  return (
    <>
      <PageHeader
        title="Knowledge base"
        subtitle={
          total === undefined
            ? "Approved entries are what the voice assistant answers from."
            : `${total} ${filter === "all" ? "" : `${filter} `}${total === 1 ? "entry" : "entries"}. Approved entries are what the voice assistant answers from.`
        }
        actions={
          <>
            <label className="flex items-center gap-2 text-xs text-ink-soft">
              <span className="font-medium uppercase tracking-wide">Status</span>
              <select
                className="input w-auto"
                value={filter}
                onChange={(e) => setFilter(e.target.value as Filter)}
                aria-label="Filter entries by status"
              >
                {FILTERS.map((f) => (
                  <option key={f} value={f}>
                    {f === "all" ? "All" : humanize(f)}
                  </option>
                ))}
              </select>
            </label>
            {isAdmin ? (
              <Button onClick={() => setShowImport((v) => !v)} aria-expanded={showImport}>
                <FileUp size={14} aria-hidden /> Import JSONL
              </Button>
            ) : null}
            <Button variant="primary" onClick={openNew}>
              <Plus size={14} aria-hidden /> New entry
            </Button>
          </>
        }
      />

      {notice ? (
        <div
          role={notice.tone === "bad" ? "alert" : "status"}
          className={
            notice.tone === "bad"
              ? "mb-3 flex items-start justify-between gap-3 rounded-md border border-[#EBC4B6] bg-[#F6E1D9] px-3 py-2 text-sm text-[#8D3C21]"
              : "mb-3 flex items-start justify-between gap-3 rounded-md border border-[#C7DBCC] bg-[#E2EDE4] px-3 py-2 text-sm text-[#3F6B49]"
          }
        >
          <span>{notice.text}</span>
          <button type="button" className="text-xs underline" onClick={() => setNotice(null)}>
            Dismiss
          </button>
        </div>
      ) : null}

      {isAdmin && showImport ? (
        <div className="mb-4">
          <ImportPanel onClose={() => setShowImport(false)} />
        </div>
      ) : null}

      <Panel flush>
        <EntriesTable
          rows={rows}
          isAdmin={isAdmin}
          now={now}
          isLoading={entries.isPending}
          error={entries.error}
          onRetry={() => void entries.refetch()}
          busyId={busyId}
          onEdit={openEdit}
          onSetStatus={(row, status) => setStatus.mutate({ id: row.entry.id, status })}
          emptyTitle={filter === "all" ? "No KB entries yet" : `No ${filter} entries`}
          emptyHint={
            filter === "all"
              ? "Create an entry with New entry, or import a JSONL file."
              : "Change the status filter to see the other entries."
          }
        />
      </Panel>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <PublishPanel isAdmin={isAdmin} />
        <PublishHistory
          records={publishes.data?.items}
          isLoading={publishes.isPending}
          error={publishes.error}
          onRetry={() => void publishes.refetch()}
        />
      </div>

      <EntryEditor target={editor} onClose={() => setEditor(null)} />
    </>
  );
}

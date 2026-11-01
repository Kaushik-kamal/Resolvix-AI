import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, History, Rocket } from "lucide-react";
import { useMemo, useState } from "react";
import { api, isApiError, qk } from "../../api";
import type { ApiError, KBPublishRecord } from "../../api";
import type { KBVersionInfo } from "../../api/types";
import { Button, DataTable, ModeBadge, Panel, RelativeTime, type Column } from "../../components";
import { formatCount, formatDateTime, parseApiDate } from "../../lib/format";
import { isMockPublish } from "./kbModel";

/** Big amber banner: a mock publish must never be mistaken for a live one. */
export function MockPublishBanner({ warnings }: { warnings: readonly string[] }) {
  const mock = warnings.filter((w) => /mock publish/i.test(w));
  return (
    <div
      role="alert"
      data-testid="mock-publish-banner"
      className="flex items-start gap-2 rounded-md border border-[#E8D3B1] bg-[#F5E9D8] px-3 py-2 text-sm font-medium text-[#80551F]"
    >
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div>
        <p>MOCK PUBLISH: the voice assistant did not receive this KB.</p>
        {mock.map((w) => (
          <p key={w} className="text-xs font-normal">
            {w}
          </p>
        ))}
      </div>
    </div>
  );
}

/**
 * Mode of the newest row of the publish history (what GET /v1/kb/publishes says), or null when the history is empty
 * or has no usable mode. Newest = latest `at`, ties broken by the higher id.
 */
export function newestPublishMode(records: readonly KBPublishRecord[] | undefined | null): "mock" | "live" | null {
  if (!records || records.length === 0) return null;
  const newest = [...records].sort(
    (a, b) => (parseApiDate(b.at)?.getTime() ?? 0) - (parseApiDate(a.at)?.getTime() ?? 0) || (b.id ?? 0) - (a.id ?? 0),
  )[0];
  return newest.mode === "mock" || newest.mode === "live" ? newest.mode : null;
}

/**
 * KBVersionInfo: version, counts, tokens and every warning. `mode` is the authoritative mock/live value from the
 * publish history (L8); the warning text is only the fallback when the history was unavailable.
 */
export function PublishResultView({ info, mode }: { info: KBVersionInfo; mode?: "mock" | "live" | null }) {
  const warnings = info.warnings ?? [];
  const mock = mode ? mode === "mock" : isMockPublish(warnings);
  const others = warnings.filter((w) => !/mock publish/i.test(w));
  return (
    <div className="space-y-3" data-testid="publish-result">
      {mock ? <MockPublishBanner warnings={warnings} /> : null}
      <div className="flex items-center gap-2 text-sm font-semibold text-ink">
        {mock ? "Resulting KB version" : "Published KB version"}
        <span className="rounded bg-bg px-1.5 py-0.5 font-mono text-xs">{info.kb_version}</span>
        <ModeBadge mode={mock ? "mock" : "live"} prefix="Publish" />
      </div>
      <dl className="grid grid-cols-4 gap-3 text-sm">
        <Stat label="Entries" value={formatCount(info.entry_count)} />
        <Stat label="FAQ entries" value={formatCount(info.faq_count)} />
        <Stat label="Tokens" value={formatCount(info.token_count)} />
        <Stat label="Activated" value={formatDateTime(info.activated_at)} small />
      </dl>
      {others.length > 0 ? (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-soft">Warnings</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-[#80551F]">
            {others.map((w) => (
              <li key={w} className="break-words">
                {w}
              </li>
            ))}
          </ul>
        </div>
      ) : mock ? null : (
        <p className="text-xs text-ink-soft">No warnings.</p>
      )}
    </div>
  );
}

function Stat({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink-soft">{label}</dt>
      <dd className={small ? "text-xs font-medium" : "text-lg font-semibold tabular-nums"}>{value}</dd>
    </div>
  );
}

/** Failure of POST /v1/kb/publish: 422 lists the runtime's problems, 502 is retryable, anything else shows the message. */
export function PublishErrorView({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const err: ApiError | null = isApiError(error) ? error : null;
  const problems = err ? Object.entries(err.details) : [];
  const upstream = err?.status === 502 || err?.code === "upstream_error";
  const rejected = err?.status === 422;
  const denied = err?.status === 403;
  return (
    <div role="alert" data-testid="publish-error" className="space-y-2 rounded-md border border-[#EBC4B6] bg-[#F6E1D9] px-3 py-2 text-sm text-[#8D3C21]">
      <p className="font-semibold">
        {denied
          ? "Publishing is for admins only."
          : rejected
            ? "The voice runtime rejected this KB. Nothing was published."
            : upstream
              ? "The voice runtime could not be reached. Nothing was published."
              : "Publish failed."}
      </p>
      <p className="text-xs">
        {err ? `${err.message} (${err.code}${err.status ? `, HTTP ${err.status}` : ""})` : error instanceof Error ? error.message : "Unknown error"}
      </p>
      {problems.length > 0 ? (
        <ul className="list-disc space-y-0.5 pl-5 text-xs">
          {problems.map(([key, problem]) => (
            <li key={key} className="break-words">
              <span className="font-mono">{key}</span>: {problem}
            </li>
          ))}
        </ul>
      ) : null}
      {upstream || err?.retryable ? (
        <p className="text-xs">This is usually temporary. Check that the voice runtime is running, then retry.</p>
      ) : null}
      {onRetry && (upstream || err?.retryable) ? (
        <Button size="sm" onClick={onRetry}>
          Retry publish
        </Button>
      ) : null}
    </div>
  );
}

export function PublishPanel({ isAdmin }: { isAdmin: boolean }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  // L8: after a publish, re-read the history right away and take the mode of its newest row (live vs mock) from there.
  // If the history cannot be read the result view falls back to the "mock publish" warning text.
  const publish = useMutation({
    mutationFn: async () => {
      const info = await api.publishKb();
      let mode: "mock" | "live" | null = null;
      try {
        const history = await queryClient.fetchQuery({
          queryKey: qk.kb.publishes,
          queryFn: ({ signal }) => api.listKbPublishes(signal),
          staleTime: 0,
        });
        mode = newestPublishMode(history.items);
      } catch {
        mode = null;
      }
      return { info, mode };
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: qk.kb.publishes }),
  });

  return (
    <Panel title="Publish to voice runtime">
      {isAdmin ? (
        <div className="space-y-3">
          <p className="text-xs text-ink-soft">
            Sends every approved, currently valid entry to the voice assistant. Drafts and archived entries are not included.
          </p>
          {confirming && !publish.isPending ? (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg px-3 py-2 text-sm">
              <span>Publish the approved KB now?</span>
              <Button
                size="sm"
                variant="primary"
                onClick={() => {
                  setConfirming(false);
                  publish.mutate();
                }}
              >
                Confirm publish
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button variant="primary" disabled={publish.isPending} onClick={() => setConfirming(true)}>
              <Rocket size={14} aria-hidden /> {publish.isPending ? "Publishing…" : "Publish KB"}
            </Button>
          )}
          {publish.isError ? <PublishErrorView error={publish.error} onRetry={() => publish.mutate()} /> : null}
          {publish.data ? <PublishResultView info={publish.data.info} mode={publish.data.mode} /> : null}
        </div>
      ) : (
        <p className="text-sm text-ink-soft">Only admins can publish the KB. Ask an admin to approve and publish your drafts.</p>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------- history
export function PublishHistory({
  records,
  isLoading,
  error,
  onRetry,
}: {
  records: KBPublishRecord[] | undefined;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const sorted = useMemo(
    () =>
      records
        ? [...records].sort(
            (a, b) => (parseApiDate(b.at)?.getTime() ?? 0) - (parseApiDate(a.at)?.getTime() ?? 0),
          )
        : undefined,
    [records],
  );

  const columns: Column<KBPublishRecord>[] = [
    {
      key: "at",
      header: "When",
      width: "7rem",
      cell: (r) => <RelativeTime value={r.at} className="whitespace-nowrap text-xs text-ink-soft" />,
    },
    {
      key: "version",
      header: "Version",
      cell: (r) => <span className="font-mono text-xs">{r.kb_version}</span>,
    },
    {
      key: "mode",
      header: "Mode",
      cell: (r) => <ModeBadge mode={r.mode ?? (isMockPublish(r.info?.warnings) ? "mock" : undefined)} prefix="Publish" />,
    },
    {
      key: "entries",
      header: "Entries / FAQ",
      align: "right",
      cell: (r) => (r.info ? `${formatCount(r.info.entry_count)} / ${formatCount(r.info.faq_count)}` : "—"),
    },
    { key: "tokens", header: "Tokens", align: "right", cell: (r) => formatCount(r.info?.token_count) },
    { key: "actor", header: "By", cell: (r) => <span className="text-xs">{r.actor ?? "—"}</span> },
    {
      key: "warnings",
      header: "Warnings",
      cell: (r) =>
        r.info?.warnings && r.info.warnings.length > 0 ? (
          <ul className="space-y-0.5 text-xs text-[#80551F]">
            {r.info.warnings.map((w) => (
              <li key={w} className="break-words">
                {w}
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-ink-faint">None</span>
        ),
    },
  ];

  return (
    <Panel
      title={
        <span className="inline-flex items-center gap-1.5">
          <History size={14} aria-hidden /> Version history
        </span>
      }
      flush
    >
      <DataTable
        caption="KB publish history, newest first"
        columns={columns}
        rows={sorted}
        rowKey={(r) => `${r.id ?? ""}|${r.at}|${r.kb_version}`}
        isLoading={isLoading}
        error={error}
        onRetry={onRetry}
        emptyTitle="Nothing published yet"
        emptyHint="Each publish is recorded here with its version, mode and warnings."
      />
    </Panel>
  );
}

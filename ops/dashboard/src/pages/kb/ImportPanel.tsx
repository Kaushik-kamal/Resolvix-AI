import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, isApiError, qk } from "../../api";
import type { KBImportResult } from "../../api";
import { Button, ErrorState, Panel } from "../../components";

/** Result of an import: counts plus the per-line errors ({line, message}). */
export function ImportResultView({ result }: { result: KBImportResult }) {
  return (
    <div className="space-y-3" aria-live="polite">
      <dl className="flex flex-wrap gap-6 text-sm">
        <div>
          <dt className="text-xs uppercase tracking-wide text-ink-soft">Imported</dt>
          <dd className="text-lg font-semibold tabular-nums" data-testid="import-imported">
            {result.imported}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-ink-soft">Flagged</dt>
          <dd
            className={result.flagged > 0 ? "text-lg font-semibold tabular-nums text-[#8D3C21]" : "text-lg font-semibold tabular-nums"}
            data-testid="import-flagged"
          >
            {result.flagged}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-ink-soft">Line errors</dt>
          <dd className="text-lg font-semibold tabular-nums" data-testid="import-error-count">
            {result.errors.length}
          </dd>
        </div>
      </dl>
      <p className="text-xs text-ink-soft">
        Each unflagged line keeps the status written in the file (approved lines are live for the next publish); flagged lines are saved as draft.
        {result.flagged > 0 ? " Flagged entries matched the injection scan and cannot be approved until their text is edited, then saved again." : ""}
      </p>
      {result.errors.length > 0 ? (
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">Lines that could not be imported</caption>
          <thead>
            <tr>
              <th scope="col" className="th w-20">
                Line
              </th>
              <th scope="col" className="th">
                Problem
              </th>
            </tr>
          </thead>
          <tbody>
            {result.errors.map((err, i) => (
              <tr key={`${err.line}-${i}`}>
                <td className="td font-mono tabular-nums">{err.line}</td>
                <td className="td break-words">{err.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-xs text-ink-soft">Every line was accepted.</p>
      )}
    </div>
  );
}

export function ImportPanel({ onClose }: { onClose?: () => void }) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);

  const upload = useMutation({
    mutationFn: (f: File) => api.importKb(f, f.name),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: qk.kb.entriesAny }),
  });

  return (
    <Panel
      title="Import JSONL"
      actions={
        onClose ? (
          <Button size="sm" variant="ghost" onClick={onClose}>
            Close
          </Button>
        ) : undefined
      }
    >
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (file) upload.mutate(file);
        }}
      >
        <div className="min-w-[16rem] flex-1">
          <label htmlFor="kb-import-file" className="label">
            KB file (one JSON entry per line, UTF-8, up to 2 MB)
          </label>
          <input
            id="kb-import-file"
            ref={inputRef}
            type="file"
            accept=".jsonl,.json,.txt,application/json,application/x-ndjson,text/plain"
            className="input"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              upload.reset();
            }}
          />
        </div>
        <Button type="submit" variant="primary" disabled={!file || upload.isPending}>
          <Upload size={14} aria-hidden /> {upload.isPending ? "Uploading…" : "Upload"}
        </Button>
      </form>
      <p className="mt-2 text-xs text-ink-faint">
        Admins only. Each unflagged entry keeps the status in the file; entries matching the injection scan are flagged and saved as draft.
      </p>

      <div className="mt-4">
        {upload.isError ? (
          <ErrorState
            error={upload.error}
            title={isApiError(upload.error) && upload.error.status === 403 ? "Importing is for admins only" : "Import rejected"}
            onRetry={isApiError(upload.error) && upload.error.status === 403 ? undefined : file ? () => upload.mutate(file) : undefined}
          />
        ) : null}
        {upload.data ? <ImportResultView result={upload.data} /> : null}
      </div>
    </Panel>
  );
}

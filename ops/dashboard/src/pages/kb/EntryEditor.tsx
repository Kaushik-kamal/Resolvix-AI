import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useId, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { api, isApiError, qk } from "../../api";
import type { KBSaveResult } from "../../api";
import { useSessionUser } from "../../auth/AuthContext";
import { Button, Drawer, LoadingState, StatusChip } from "../../components";
import { FlaggedBadge } from "./EntriesTable";
import { validateKbForm, type KbErrors, type KbField, type KbFormValues } from "./kbModel";

export interface EditorTarget {
  mode: "new" | "edit";
  values: KbFormValues;
  /** status of the stored entry when editing */
  currentStatus?: "draft" | "approved" | "archived";
  flagged?: boolean;
  /** shown above the form, e.g. "Prefilled from gap cluster Bus Noida" */
  note?: string;
  /** changes whenever a new target replaces the old one, so the form state resets */
  nonce?: number;
}

interface FieldProps {
  name: KbField;
  label: string;
  error?: string;
  hint?: ReactNode;
  required?: boolean;
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}

function Field({ name, label, error, hint, required, children }: FieldProps) {
  const base = useId();
  const id = `${base}-${name}`;
  const errId = `${id}-err`;
  const hintId = `${id}-hint`;
  const describedBy = [error ? errId : null, hint ? hintId : null].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label htmlFor={id} className="label">
        {label}
        {required ? <span aria-hidden className="text-p1"> *</span> : null}
      </label>
      {children({ id, describedBy, invalid: !!error })}
      {hint ? (
        <p id={hintId} className="mt-1 text-xs text-ink-faint">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errId} role="alert" className="mt-1 text-xs font-medium text-[#8D3C21]">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Lists the field problems a 422 returned (error.details is {key: problem}). */
function SaveError({ error }: { error: unknown }) {
  if (!isApiError(error)) {
    return (
      <div role="alert" className="rounded-md border border-[#EBC4B6] bg-[#F6E1D9] px-3 py-2 text-sm text-[#8D3C21]">
        Could not save: {error instanceof Error ? error.message : "unknown error"}
      </div>
    );
  }
  const details = Object.entries(error.details);
  return (
    <div role="alert" className="rounded-md border border-[#EBC4B6] bg-[#F6E1D9] px-3 py-2 text-sm text-[#8D3C21]">
      {error.status === 409 ? (
        <p className="mb-1 font-semibold" data-testid="save-conflict">
          This entry is approved or archived and staff cannot overwrite it. Nothing was saved. Ask an admin to change it,
          or write your wording as a new entry with a new id.
        </p>
      ) : null}
      {error.status === 403 ? (
        <p className="mb-1 font-semibold" data-testid="save-forbidden">
          Your role is not allowed to save this entry. Nothing was saved.
        </p>
      ) : null}
      <p className="font-medium">
        Could not save: {error.message} ({error.code}
        {error.status ? `, HTTP ${error.status}` : ""})
      </p>
      {details.length > 0 ? (
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">
          {details.map(([key, problem]) => (
            <li key={key} className="break-words">
              {problem}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function SaveNotice({ result }: { result: KBSaveResult }) {
  return (
    <div role="status" className="space-y-2">
      <div className="rounded-md border border-[#C7DBCC] bg-[#E2EDE4] px-3 py-2 text-sm text-[#3F6B49]">
        <strong>{result.id}</strong> saved as draft; an admin must approve it before it is published to the voice assistant.
      </div>
      {result.flagged ? (
        <div role="alert" className="rounded-md border border-[#E8D3B1] bg-[#F5E9D8] px-3 py-2 text-sm text-[#80551F]">
          <strong>Flagged:</strong> the injection scan matched this text (for example &ldquo;ignore previous instructions&rdquo;,
          &ldquo;system prompt&rdquo; or &ldquo;act as&rdquo;). It cannot be approved until you edit the wording and save again.
        </div>
      ) : null}
    </div>
  );
}

export interface EntryEditorProps {
  target: EditorTarget | null;
  onClose: () => void;
}

/**
 * Create/edit form for every KBEntry field, in a drawer. Saving always creates a draft (the server forces it).
 * Remount with a new `key` per target so the form state resets.
 */
export function EntryEditor({ target, onClose }: EntryEditorProps) {
  return (
    <Drawer
      open={target !== null}
      onClose={onClose}
      size="xl"
      title={target?.mode === "edit" ? `Edit ${target.values.id}` : "New KB entry"}
      headerExtra={
        target?.mode === "edit" ? (
          <>
            {target.currentStatus ? <StatusChip status={target.currentStatus} /> : null}
            {target.flagged ? <FlaggedBadge /> : null}
          </>
        ) : null
      }
      footer={
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-ink-soft">Entries are saved as draft; an admin must approve them before publishing.</p>
          <div className="flex gap-2">
            <Button onClick={onClose}>Close</Button>
            <Button type="submit" form="kb-entry-form" variant="primary">
              <Save size={14} aria-hidden /> Save as draft
            </Button>
          </div>
        </div>
      }
    >
      {target ? <EntryForm key={target.nonce ?? 0} target={target} /> : null}
    </Drawer>
  );
}

function EntryForm({ target }: { target: EditorTarget }) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState<KbFormValues>(target.values);
  const [touched, setTouched] = useState<Partial<Record<KbField, boolean>>>({});
  const [submitted, setSubmitted] = useState(false);

  const departments = useQuery({
    queryKey: qk.config.departments,
    queryFn: ({ signal }) => api.getDepartments(signal),
    staleTime: Infinity,
  });

  const save = useMutation({
    mutationFn: (entry: NonNullable<ReturnType<typeof validateKbForm>["entry"]>) => api.saveKbEntry(entry),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: qk.kb.entriesAny }),
  });

  const { errors: allErrors } = useMemo(() => validateKbForm(values), [values]);
  const errors: KbErrors = {};
  for (const key of Object.keys(allErrors) as KbField[]) {
    if (submitted || touched[key]) errors[key] = allErrors[key];
  }

  const set = <K extends KbField>(key: K, value: KbFormValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    save.reset();
  };
  const blur = (key: KbField) => () => setTouched((prev) => ({ ...prev, [key]: true }));

  const deptOptions = useMemo(() => {
    const list = (departments.data?.departments ?? []).map((d) => ({ key: d.key, name: d.name }));
    if (values.department && !list.some((d) => d.key === values.department)) {
      list.push({ key: values.department, name: `${values.department} (not in departments.yaml)` });
    }
    return list;
  }, [departments.data, values.department]);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    const { entry } = validateKbForm(values);
    if (entry) save.mutate(entry);
  };

  const editingApproved = target.mode === "edit" && target.currentStatus === "approved";
  const isStaff = useSessionUser()?.role === "staff";

  return (
    <form id="kb-entry-form" onSubmit={onSubmit} noValidate className="space-y-4">
      {target.note ? (
        <p className="rounded-md border border-[#CBD8DF] bg-[#E3EAEE] px-3 py-2 text-xs text-[#40596A]">{target.note}</p>
      ) : null}
      {editingApproved && isStaff ? (
        <p className="rounded-md border border-[#E8D3B1] bg-[#F5E9D8] px-3 py-2 text-xs text-[#80551F]" data-testid="approved-staff-note">
          This entry is approved. Staff can save drafts but cannot overwrite an approved or archived entry: saving here
          will be refused (HTTP 409). Ask an admin to change it, or copy the wording into a new entry.
        </p>
      ) : editingApproved ? (
        <p className="rounded-md border border-[#E8D3B1] bg-[#F5E9D8] px-3 py-2 text-xs text-[#80551F]">
          This entry is approved. Saving your changes turns it back into a draft until an admin approves it again.
        </p>
      ) : null}

      {save.data ? <SaveNotice result={save.data} /> : null}
      {save.isError ? <SaveError error={save.error} /> : null}

      <div className="grid grid-cols-2 gap-4">
        <Field name="id" label="ID" required error={errors.id} hint="e.g. FEE-012: 2-4 capital letters, dash, 3-4 digits.">
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              className="input font-mono"
              value={values.id}
              readOnly={target.mode === "edit"}
              onChange={(e) => set("id", e.target.value.toUpperCase())}
              onBlur={blur("id")}
              aria-invalid={invalid}
              aria-describedby={describedBy}
              autoComplete="off"
              spellCheck={false}
            />
          )}
        </Field>
        <Field name="department" label="Department" required error={errors.department}>
          {({ id, describedBy, invalid }) => (
            <select
              id={id}
              className="input"
              value={values.department}
              onChange={(e) => set("department", e.target.value)}
              onBlur={blur("department")}
              aria-invalid={invalid}
              aria-describedby={describedBy}
            >
              <option value="">{departments.isPending ? "Loading departments…" : "Select a department"}</option>
              {deptOptions.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.name}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>
      {departments.isError ? (
        <p role="alert" className="text-xs text-[#8D3C21]">
          Could not load departments; try again later.
        </p>
      ) : null}
      {departments.isPending && target.mode === "new" ? <LoadingState label="Loading departments…" className="p-0" /> : null}

      <Field
        name="questionVariants"
        label="Question variants"
        required
        error={errors.questionVariants}
        hint="One way of asking per line, in English, Hindi or Hinglish. At least one."
      >
        {({ id, describedBy, invalid }) => (
          <textarea
            id={id}
            className="input min-h-[7rem]"
            rows={5}
            value={values.questionVariants}
            onChange={(e) => set("questionVariants", e.target.value)}
            onBlur={blur("questionVariants")}
            aria-invalid={invalid}
            aria-describedby={describedBy}
          />
        )}
      </Field>

      <Field name="answerEn" label="Answer (English)" required error={errors.answerEn}>
        {({ id, describedBy, invalid }) => (
          <textarea
            id={id}
            className="input min-h-[7rem]"
            rows={5}
            value={values.answerEn}
            onChange={(e) => set("answerEn", e.target.value)}
            onBlur={blur("answerEn")}
            aria-invalid={invalid}
            aria-describedby={describedBy}
          />
        )}
      </Field>

      <Field name="answerHi" label="Answer (Hindi)" error={errors.answerHi} hint="Optional.">
        {({ id, describedBy, invalid }) => (
          <textarea
            id={id}
            className="input min-h-[5rem]"
            rows={3}
            lang="hi"
            value={values.answerHi}
            onChange={(e) => set("answerHi", e.target.value)}
            aria-invalid={invalid}
            aria-describedby={describedBy}
          />
        )}
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field name="sourceTitle" label="Source title" required error={errors.sourceTitle}>
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              className="input"
              value={values.sourceTitle}
              onChange={(e) => set("sourceTitle", e.target.value)}
              onBlur={blur("sourceTitle")}
              aria-invalid={invalid}
              aria-describedby={describedBy}
              placeholder="Fee Notice 2026-27"
            />
          )}
        </Field>
        <Field name="sourceRef" label="Source reference" error={errors.sourceRef} hint="Optional: page or URL.">
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              className="input"
              value={values.sourceRef}
              onChange={(e) => set("sourceRef", e.target.value)}
              aria-invalid={invalid}
              aria-describedby={describedBy}
              placeholder="p.1"
            />
          )}
        </Field>
        <Field name="validFrom" label="Valid from" error={errors.validFrom} hint="Optional.">
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              type="date"
              className="input"
              value={values.validFrom}
              onChange={(e) => set("validFrom", e.target.value)}
              onBlur={blur("validFrom")}
              aria-invalid={invalid}
              aria-describedby={describedBy}
            />
          )}
        </Field>
        <Field name="validUntil" label="Valid until" error={errors.validUntil} hint="Optional. Expired entries leave the published KB.">
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              type="date"
              className="input"
              value={values.validUntil}
              onChange={(e) => set("validUntil", e.target.value)}
              onBlur={blur("validUntil")}
              aria-invalid={invalid}
              aria-describedby={describedBy}
            />
          )}
        </Field>
      </div>

      <Field name="tags" label="Tags" error={errors.tags} hint="Comma separated. Optional.">
        {({ id, describedBy, invalid }) => (
          <input
            id={id}
            className="input"
            value={values.tags}
            onChange={(e) => set("tags", e.target.value)}
            aria-invalid={invalid}
            aria-describedby={describedBy}
            placeholder="fees, deadline"
          />
        )}
      </Field>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={values.isFaq}
          onChange={(e) => set("isFaq", e.target.checked)}
          className="h-4 w-4 accent-[#7A5A40]"
        />
        <span>Frequently asked question (is_faq)</span>
      </label>
    </form>
  );
}

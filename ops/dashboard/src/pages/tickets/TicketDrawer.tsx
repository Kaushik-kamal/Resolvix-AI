import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookPlus, Eye, EyeOff, ShieldCheck } from "lucide-react";
import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, qk, type Me, type TicketPatch, type TicketRow } from "../../api";
import {
  Button,
  Drawer,
  ErrorState,
  LoadingState,
  MaskedNumber,
  PriorityBadge,
  RelativeTime,
  StatusChip,
  errorMessage,
} from "../../components";
import { useReveal } from "../../hooks/useReveal";
import { formatDateTime, humanize } from "../../lib/format";
import { buildTicketDraftSeed, KB_DRAFT_STATE_KEY } from "../kb/draftSeed";
import { buildStatusPatch, canDraftFromResolution, extractResolution, mayTriggerSms, parseNote, parsePriorityReason, TICKET_STATUSES } from "./ticketLogic";
import { TicketTimeline } from "./TicketTimeline";
import { TicketTranscript } from "./TicketTranscript";

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="mb-5">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-soft">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="mt-0.5 break-words text-[13px] text-ink">{children}</dd>
    </div>
  );
}

function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="mt-1.5 rounded border border-p1/40 bg-[#F6E1D9] px-2 py-1 text-xs text-[#8D3C21]">
      {errorMessage(error)}
    </p>
  );
}

export interface TicketDrawerProps {
  ticketId: string;
  onClose: () => void;
  /** assignees already seen in the list: suggestions for the assignee field */
  knownAssignees?: string[];
}

/**
 * Detail drawer for one ticket. Mount it only while it is open (the page renders it per `?ticket=` value):
 * closing unmounts it, which also hides revealed numbers again.
 */
export function TicketDrawer({ ticketId, onClose, knownAssignees = [] }: TicketDrawerProps) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // The masked detail keeps refreshing from the stream. The revealed copy is a separate, explicit one-shot fetch (L12):
  // every reveal=true request is audited, so SSE refetches never ask for it again, and Hide / closing the drawer
  // removes it from the query cache.
  const detail = useQuery({
    queryKey: qk.tickets.detail(ticketId, false),
    queryFn: ({ signal }) => api.getTicket(ticketId, {}, signal),
  });
  const reveal = useReveal(qk.tickets.detail(ticketId, true), (signal) => api.getTicket(ticketId, { reveal: true }, signal));
  const revealed = reveal.revealed;
  const events = useQuery({
    queryKey: qk.tickets.events(ticketId),
    queryFn: ({ signal }) => api.listTicketEvents(ticketId, signal),
  });
  // The session user is already cached by the auth guard; enabled:false only reads it.
  const me = useQuery<Me | null>({ queryKey: qk.me, queryFn: () => null, enabled: false }).data ?? null;

  const ticket = detail.data;
  const revealedCopy = reveal.data;
  const revealActive = revealed && !!revealedCopy;
  const callerNumber = revealedCopy?.caller_number ?? ticket?.caller_number;
  const callbackNumber = revealedCopy?.callback_number ?? ticket?.callback_number;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: qk.tickets.lists() });
    void queryClient.invalidateQueries({ queryKey: qk.tickets.detailAny(ticketId) });
    void queryClient.invalidateQueries({ queryKey: qk.tickets.events(ticketId) });
  };

  const patch = useMutation({
    mutationFn: (body: TicketPatch) => api.patchTicket(ticketId, body),
    onSettled: refresh,
  });

  const [smsHint, setSmsHint] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const apply = (body: TicketPatch, onOk?: (saved: TicketRow) => void, message?: string) => {
    setSmsHint(false);
    setDone(null);
    patch.mutate(body, {
      onSuccess: (saved) => {
        if (message) setDone(message);
        onOk?.(saved);
      },
    });
  };

  // ---- status + resolution
  const [nextStatus, setNextStatus] = useState<string>("");
  const [resolution, setResolution] = useState("");
  useEffect(() => {
    if (ticket?.status) setNextStatus(ticket.status);
  }, [ticket?.status]);
  const selectedStatus = nextStatus || ticket?.status || "";
  const statusPatch = ticket ? buildStatusPatch({ currentStatus: ticket.status, nextStatus: selectedStatus, resolution }) : {};
  const showResolution = selectedStatus === "resolved" || selectedStatus === "closed";

  const submitStatus = (event: FormEvent) => {
    event.preventDefault();
    if (!ticket || Object.keys(statusPatch).length === 0) return;
    const statusChanged = statusPatch.status !== undefined;
    apply(statusPatch, () => {
      setResolution("");
      if (statusChanged && mayTriggerSms(ticket)) setSmsHint(true);
    }, statusChanged ? `Status set to ${humanize(statusPatch.status)}.` : "Resolution saved as a note.");
  };

  // ---- assignee
  const [assignee, setAssignee] = useState("");
  useEffect(() => {
    setAssignee(ticket?.assignee ?? "");
  }, [ticket?.assignee]);
  const assigneeListId = useId();
  const assigneeOptions = Array.from(new Set([...(me ? [me.email] : []), ...knownAssignees])).filter(Boolean);
  const assigneeChanged = assignee.trim() !== (ticket?.assignee ?? "");
  const submitAssignee = (event: FormEvent) => {
    event.preventDefault();
    if (!assigneeChanged) return;
    // The contract cannot clear an assignee (null = "no change"), so unassigning sends an empty string.
    apply({ assignee: assignee.trim() }, undefined, assignee.trim() ? `Assigned to ${assignee.trim()}.` : "Assignee cleared.");
  };

  // ---- notes
  const [note, setNote] = useState("");
  const submitNote = (event: FormEvent) => {
    event.preventDefault();
    const text = note.trim();
    if (!text) return;
    apply({ note: text }, () => setNote(""), "Note added.");
  };

  const parsedReason = parsePriorityReason(ticket?.priority_reason);
  const fields = Object.entries(ticket?.collected_fields ?? {});
  const notes = (ticket?.notes ?? []).map(parseNote);

  let body: ReactNode;
  if (detail.isError && !ticket) {
    body = <ErrorState error={detail.error} title="Could not load the ticket" onRetry={() => void detail.refetch()} />;
  } else if (!ticket) {
    body = <LoadingState label="Loading ticket…" variant="skeleton" rows={6} />;
  } else {
    body = (
      <>
        <Section title="Summary">
          <p className="text-[13px] leading-relaxed text-ink">{ticket.summary}</p>
        </Section>

        <Section title="Brief for staff">
          {ticket.brief ? (
            <p className="whitespace-pre-wrap rounded-md border border-line bg-bg px-3 py-2 text-[13px] leading-relaxed text-ink">{ticket.brief}</p>
          ) : (
            <p className="text-xs text-ink-faint">No brief was generated for this ticket.</p>
          )}
        </Section>

        <Section title="Priority reason">
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            {parsedReason.ruleId ? (
              <span
                className="rounded border border-[#E8D3B1] bg-[#F5E9D8] px-1.5 py-0.5 font-mono text-[11px] font-semibold text-[#80551F]"
                data-testid="rule-id"
                title="Urgency rule that set the priority"
              >
                {parsedReason.ruleId}
              </span>
            ) : null}
            <span>{parsedReason.text || (parsedReason.ruleId ? "" : "No reason recorded")}</span>
          </div>
        </Section>

        <Section
          title="Caller"
          aside={
            <Button
              size="sm"
              variant="secondary"
              onClick={reveal.toggle}
              aria-pressed={revealed}
              disabled={(!ticket.caller_number && !ticket.callback_number) || reveal.pending}
            >
              {revealed ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}
              {revealed ? "Hide numbers" : "Reveal numbers"}
            </Button>
          }
        >
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            <Field label="Caller number">
              <MaskedNumber value={callerNumber} revealed={revealActive} />
            </Field>
            <Field label="Callback number">
              <MaskedNumber value={callbackNumber} revealed={revealActive} />
            </Field>
            <Field label="Callback requested">{ticket.callback_requested ? "Yes" : "No"}</Field>
            <Field label="Call">{ticket.call_id ?? "—"}</Field>
          </dl>
          {revealActive ? (
            <p className="mt-2 inline-flex items-center gap-1 rounded bg-[#F5E9D8] px-2 py-1 text-xs text-[#80551F]" role="status">
              <ShieldCheck size={13} aria-hidden /> Numbers revealed, access recorded in the audit log. They are hidden again when you close this panel.
            </p>
          ) : null}
          <InlineError error={reveal.error} />
        </Section>

        <Section title="Details">
          <dl className="grid grid-cols-3 gap-x-4 gap-y-2">
            <Field label="Type">{humanize(ticket.type)}</Field>
            <Field label="Department">{humanize(ticket.department)}</Field>
            <Field label="Assignee">{ticket.assignee || "Unassigned"}</Field>
            <Field label="Created">{formatDateTime(ticket.created_at)}</Field>
            <Field label="Updated">
              <RelativeTime value={ticket.updated_at} />
            </Field>
            <Field label="Resolved">{ticket.resolved_at ? formatDateTime(ticket.resolved_at) : "—"}</Field>
          </dl>
        </Section>

        <Section title="Collected fields">
          {fields.length === 0 ? (
            <p className="text-xs text-ink-faint">Nothing was collected from the caller.</p>
          ) : (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-line bg-surface px-3 py-2">
              {fields.map(([key, value]) => (
                <Field key={key} label={humanize(key)}>
                  {value}
                </Field>
              ))}
            </dl>
          )}
        </Section>

        {ticket.transcript_excerpt ? (
          <Section title="Transcript excerpt">
            <p className="whitespace-pre-wrap rounded-md border border-line bg-bg px-3 py-2 text-xs text-ink-soft">{ticket.transcript_excerpt}</p>
          </Section>
        ) : null}

        <Section title="Update ticket">
          <form onSubmit={submitStatus} className="space-y-2" aria-label="Change status">
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <label className="label" htmlFor={`${assigneeListId}-status`}>
                  Status
                </label>
                <select
                  id={`${assigneeListId}-status`}
                  className="input"
                  value={selectedStatus}
                  onChange={(event) => setNextStatus(event.target.value)}
                  disabled={patch.isPending}
                >
                  {TICKET_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {humanize(status)}
                    </option>
                  ))}
                </select>
              </div>
              <Button type="submit" variant="primary" disabled={patch.isPending || Object.keys(statusPatch).length === 0}>
                {statusPatch.status ? "Apply status" : "Save resolution"}
              </Button>
            </div>
            {showResolution ? (
              <div>
                <label className="label" htmlFor={`${assigneeListId}-resolution`}>
                  Resolution
                </label>
                <textarea
                  id={`${assigneeListId}-resolution`}
                  className="input min-h-[64px]"
                  rows={2}
                  placeholder="What was done to resolve this?"
                  value={resolution}
                  onChange={(event) => setResolution(event.target.value)}
                  disabled={patch.isPending}
                />
              </div>
            ) : null}
          </form>

          <form onSubmit={submitAssignee} className="mt-3 flex items-end gap-2" aria-label="Change assignee">
            <div className="flex-1">
              <label className="label" htmlFor={`${assigneeListId}-assignee`}>
                Assignee
              </label>
              <input
                id={`${assigneeListId}-assignee`}
                className="input"
                list={assigneeListId}
                value={assignee}
                onChange={(event) => setAssignee(event.target.value)}
                placeholder="staff email"
                disabled={patch.isPending}
              />
              <datalist id={assigneeListId}>
                {assigneeOptions.map((option) => (
                  <option key={option} value={option} />
                ))}
              </datalist>
            </div>
            {me && assignee !== me.email ? (
              <Button onClick={() => setAssignee(me.email)} disabled={patch.isPending}>
                Assign to me
              </Button>
            ) : null}
            <Button type="submit" variant="primary" disabled={patch.isPending || !assigneeChanged}>
              Save assignee
            </Button>
          </form>

          {smsHint ? (
            <p className="mt-2 rounded border border-[#C7DBCC] bg-[#E2EDE4] px-2 py-1 text-xs text-[#3F6B49]" role="status" data-testid="sms-hint">
              The caller may receive a status SMS now (shown as SMS mock or live in the timeline below).
            </p>
          ) : null}
          {done && !patch.isError ? (
            <p className="mt-2 text-xs text-ink-soft" role="status">
              {done}
            </p>
          ) : null}
          <InlineError error={patch.isError ? patch.error : null} />
        </Section>

        <Section title={`Notes (${notes.length})`}>
          {notes.length === 0 ? (
            <p className="mb-2 text-xs text-ink-faint">No notes yet.</p>
          ) : (
            <ul className="mb-2 space-y-1.5" aria-label="Notes">
              {notes.map((n, index) => (
                <li key={index} className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[13px]">
                  <div className="flex flex-wrap justify-between gap-2 text-[11px] text-ink-faint">
                    <span>{n.actor ?? "Note"}</span>
                    {n.at ? <RelativeTime value={n.at} /> : null}
                  </div>
                  <p className="whitespace-pre-wrap">{n.text}</p>
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={submitNote} className="flex items-end gap-2" aria-label="Add note">
            <div className="flex-1">
              <label className="label" htmlFor={`${assigneeListId}-note`}>
                New note
              </label>
              <textarea
                id={`${assigneeListId}-note`}
                className="input min-h-[52px]"
                rows={2}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                disabled={patch.isPending}
              />
            </div>
            <Button type="submit" variant="primary" disabled={patch.isPending || !note.trim()}>
              Add note
            </Button>
          </form>
        </Section>

        {canDraftFromResolution(ticket) ? (
          <Section title="Knowledge base">
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                onClick={() => {
                  const seed = buildTicketDraftSeed(ticket, extractResolution(ticket.notes));
                  navigate("/kb", { state: { [KB_DRAFT_STATE_KEY]: seed } });
                }}
              >
                <BookPlus size={14} aria-hidden /> Create KB draft from resolution
              </Button>
              <p className="min-w-0 flex-1 text-xs text-ink-faint">
                Opens the KB editor with this summary as the question and the resolution as the answer. You review it
                and save it as a draft; an admin approves it.
              </p>
            </div>
          </Section>
        ) : null}

        <Section title="Transcript">
          <TicketTranscript callId={ticket.call_id} />
        </Section>

        <Section title="Timeline">
          <TicketTimeline
            events={events.data?.items}
            isLoading={events.isPending}
            error={events.error}
            onRetry={() => void events.refetch()}
          />
        </Section>
      </>
    );
  }

  return (
    <Drawer
      open
      onClose={onClose}
      size="lg"
      title={ticketId}
      subtitle={ticket ? `${humanize(ticket.department)} · ${humanize(ticket.type)}` : undefined}
      headerExtra={
        ticket ? (
          <>
            <PriorityBadge priority={ticket.priority} size="md" />
            <StatusChip status={ticket.status} />
          </>
        ) : null
      }
    >
      {body}
    </Drawer>
  );
}

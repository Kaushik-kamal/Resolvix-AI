/** Pure KB helpers: form values <-> KBEntry, validation matching the KBEntry model, expiry logic. */
import type { KBEntry } from "../../api/types";
import { istDateKey } from "../../lib/format";
import type { KbDraftSeed } from "./draftSeed";

/** KBEntry.id pattern from resolvix_contracts. */
export const KB_ID_PATTERN = /^[A-Z]{2,4}-\d{3,4}$/;
/** A valid_until fewer than this many days away (today counts as 0) gets a warning. */
export const EXPIRY_WARN_DAYS = 14;

export interface KbFormValues {
  id: string;
  department: string;
  /** one question per line */
  questionVariants: string;
  answerEn: string;
  answerHi: string;
  sourceTitle: string;
  sourceRef: string;
  /** YYYY-MM-DD or "" */
  validFrom: string;
  validUntil: string;
  /** comma separated */
  tags: string;
  isFaq: boolean;
}
export type KbField = keyof KbFormValues;
export type KbErrors = Partial<Record<KbField, string>>;

export function emptyFormValues(): KbFormValues {
  return {
    id: "",
    department: "",
    questionVariants: "",
    answerEn: "",
    answerHi: "",
    sourceTitle: "",
    sourceRef: "",
    validFrom: "",
    validUntil: "",
    tags: "",
    isFaq: false,
  };
}

export function valuesFromEntry(entry: KBEntry): KbFormValues {
  return {
    id: entry.id,
    department: entry.department,
    questionVariants: (entry.question_variants ?? []).join("\n"),
    answerEn: entry.answer_en ?? "",
    answerHi: entry.answer_hi ?? "",
    sourceTitle: entry.source_title ?? "",
    sourceRef: entry.source_ref ?? "",
    validFrom: entry.valid_from ?? "",
    validUntil: entry.valid_until ?? "",
    tags: (entry.tags ?? []).join(", "),
    isFaq: entry.is_faq ?? false,
  };
}

/**
 * Prefill for "Draft KB entry" on a gap (department, question variants, id prefix) or "Create KB draft from resolution"
 * on a ticket (the same, plus the answer and the source title when the seed carries them).
 */
export function valuesFromSeed(seed: KbDraftSeed): KbFormValues {
  return {
    ...emptyFormValues(),
    id: `${seed.idPrefix}-`,
    department: seed.department ?? "",
    questionVariants: seed.questionVariants.join("\n"),
    answerEn: seed.answerEn ?? "",
    sourceTitle: seed.sourceTitle ?? "",
  };
}

/** Non-blank trimmed lines. */
export function parseLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/** Comma (or newline) separated tags, trimmed, de-duplicated, order kept. */
export function parseTags(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of text.split(/[,\n]/)) {
    const tag = part.trim();
    if (tag && !seen.has(tag)) {
      seen.add(tag);
      out.push(tag);
    }
  }
  return out;
}

/** True for a real calendar date written YYYY-MM-DD. */
export function isIsoDate(value: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!m) return false;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const date = new Date(Date.UTC(y, mo - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d;
}

export interface KbValidation {
  errors: KbErrors;
  /** the request body when there are no errors (status is always "draft": the server stores drafts anyway) */
  entry: KBEntry | null;
}

/**
 * Client-side validation that mirrors resolvix_contracts.KBEntry (id pattern, department, question_variants min 1,
 * ISO dates) plus the minimum that makes an entry usable: a non-blank answer_en and source_title, and
 * valid_until not before valid_from.
 */
export function validateKbForm(values: KbFormValues): KbValidation {
  const errors: KbErrors = {};
  const id = values.id.trim();
  if (!id) errors.id = "ID is required, e.g. FEE-012.";
  else if (!KB_ID_PATTERN.test(id)) errors.id = "Use 2-4 capital letters, a dash, then 3-4 digits (FEE-012).";

  if (!values.department.trim()) errors.department = "Choose a department.";

  const variants = parseLines(values.questionVariants);
  if (variants.length < 1) errors.questionVariants = "Add at least one question variant (one per line).";

  if (!values.answerEn.trim()) errors.answerEn = "The English answer is required.";
  if (!values.sourceTitle.trim()) errors.sourceTitle = "Source title is required (where the answer comes from).";

  const from = values.validFrom.trim();
  const until = values.validUntil.trim();
  if (from && !isIsoDate(from)) errors.validFrom = "Use a valid date (YYYY-MM-DD).";
  if (until && !isIsoDate(until)) errors.validUntil = "Use a valid date (YYYY-MM-DD).";
  if (!errors.validFrom && !errors.validUntil && from && until && until < from) {
    errors.validUntil = "Valid until cannot be before valid from.";
  }

  if (Object.keys(errors).length > 0) return { errors, entry: null };

  const entry: KBEntry = {
    id,
    department: values.department.trim(),
    question_variants: variants as [string, ...string[]],
    answer_en: values.answerEn.trim(),
    answer_hi: values.answerHi.trim() || null,
    source_title: values.sourceTitle.trim(),
    source_ref: values.sourceRef.trim() || null,
    valid_from: from || null,
    valid_until: until || null,
    tags: parseTags(values.tags),
    is_faq: values.isFaq,
    status: "draft",
  };
  return { errors, entry };
}

// ---------------------------------------------------------------- expiry
export type ExpiryInfo =
  | { kind: "none" }
  | { kind: "ok"; days: number }
  | { kind: "soon"; days: number }
  | { kind: "expired"; days: number };

const DAY_MS = 86_400_000;

function dayNumber(key: string): number {
  const [y, m, d] = key.split("-").map(Number) as [number, number, number];
  return Math.round(Date.UTC(y, m - 1, d) / DAY_MS);
}

/**
 * Days from today (IST calendar date) until valid_until. 0 = expires today (still valid today), negative = expired.
 * kind "soon" = fewer than EXPIRY_WARN_DAYS days left. A missing or unparsable date gives kind "none".
 */
export function expiryInfo(validUntil: string | null | undefined, now: Date = new Date()): ExpiryInfo {
  if (!validUntil || !isIsoDate(validUntil)) return { kind: "none" };
  const days = dayNumber(validUntil) - dayNumber(istDateKey(now));
  if (days < 0) return { kind: "expired", days };
  if (days < EXPIRY_WARN_DAYS) return { kind: "soon", days };
  return { kind: "ok", days };
}

export function expiryLabel(info: ExpiryInfo): string {
  switch (info.kind) {
    case "none":
      return "";
    case "expired":
      return info.days === -1 ? "Expired yesterday" : `Expired ${-info.days} days ago`;
    case "soon":
      return info.days === 0 ? "Expires today" : info.days === 1 ? "Expires tomorrow" : `Expires in ${info.days} days`;
    default:
      return `${info.days} days left`;
  }
}

/** Publish results from the mock runtime carry a "mock publish: ..." warning. */
export function isMockPublish(warnings: readonly string[] | undefined | null): boolean {
  return !!warnings?.some((w) => /mock publish/i.test(w));
}

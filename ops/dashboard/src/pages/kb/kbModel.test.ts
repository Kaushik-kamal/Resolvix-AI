import { describe, expect, it } from "vitest";
import { buildDraftSeed, readDraftSeed, suggestIdPrefix, KB_DRAFT_STATE_KEY } from "./draftSeed";
import {
  EXPIRY_WARN_DAYS,
  emptyFormValues,
  expiryInfo,
  expiryLabel,
  isIsoDate,
  isMockPublish,
  parseLines,
  parseTags,
  validateKbForm,
  valuesFromEntry,
  valuesFromSeed,
  type KbFormValues,
} from "./kbModel";

// 2026-10-31 12:00 IST
const NOW = new Date("2026-10-31T06:30:00Z");

describe("expiryInfo", () => {
  it("has no warning without a date", () => {
    expect(expiryInfo(null, NOW)).toEqual({ kind: "none" });
    expect(expiryInfo(undefined, NOW)).toEqual({ kind: "none" });
    expect(expiryInfo("not-a-date", NOW)).toEqual({ kind: "none" });
  });

  it("warns when fewer than 14 days are left, counted in IST calendar days", () => {
    expect(expiryInfo("2026-10-31", NOW)).toEqual({ kind: "soon", days: 0 });
    expect(expiryInfo("2026-11-01", NOW)).toEqual({ kind: "soon", days: 1 });
    expect(expiryInfo("2026-11-13", NOW)).toEqual({ kind: "soon", days: 13 });
  });

  it("does not warn at exactly 14 days or later", () => {
    expect(EXPIRY_WARN_DAYS).toBe(14);
    expect(expiryInfo("2026-11-14", NOW)).toEqual({ kind: "ok", days: 14 });
    expect(expiryInfo("2027-03-01", NOW).kind).toBe("ok");
  });

  it("marks past dates as expired", () => {
    expect(expiryInfo("2026-10-30", NOW)).toEqual({ kind: "expired", days: -1 });
    expect(expiryLabel(expiryInfo("2026-10-30", NOW))).toBe("Expired yesterday");
    expect(expiryLabel(expiryInfo("2026-10-20", NOW))).toBe("Expired 11 days ago");
  });

  it("uses the IST date, not the UTC date, around midnight", () => {
    // 2026-10-31 20:00 UTC is 01:30 IST on 1 Nov: an entry valid until 31 Oct has expired in IST
    const lateUtc = new Date("2026-10-31T20:00:00Z");
    expect(expiryInfo("2026-10-31", lateUtc)).toEqual({ kind: "expired", days: -1 });
    expect(expiryInfo("2026-11-01", lateUtc)).toEqual({ kind: "soon", days: 0 });
  });

  it("writes readable labels", () => {
    expect(expiryLabel(expiryInfo("2026-10-31", NOW))).toBe("Expires today");
    expect(expiryLabel(expiryInfo("2026-11-01", NOW))).toBe("Expires tomorrow");
    expect(expiryLabel(expiryInfo("2026-11-08", NOW))).toBe("Expires in 8 days");
    expect(expiryLabel({ kind: "none" })).toBe("");
  });
});

describe("parsing helpers", () => {
  it("parseLines drops blanks and trims", () => {
    expect(parseLines("  a \n\n b\r\n   \nc")).toEqual(["a", "b", "c"]);
    expect(parseLines("")).toEqual([]);
  });
  it("parseTags splits on commas, trims and de-duplicates", () => {
    expect(parseTags("fees, deadline ,, fees,Late")).toEqual(["fees", "deadline", "Late"]);
  });
  it("isIsoDate rejects impossible dates", () => {
    expect(isIsoDate("2026-02-28")).toBe(true);
    expect(isIsoDate("2026-02-30")).toBe(false);
    expect(isIsoDate("31/10/2026")).toBe(false);
  });
  it("isMockPublish looks for the mock warning", () => {
    expect(isMockPublish(["mock publish: nothing was sent to the voice runtime"])).toBe(true);
    expect(isMockPublish(["token budget 90% used"])).toBe(false);
    expect(isMockPublish(undefined)).toBe(false);
  });
});

function valid(overrides: Partial<KbFormValues> = {}): KbFormValues {
  return {
    ...emptyFormValues(),
    id: "FEE-012",
    department: "accounts",
    questionVariants: "When is the fee due?\nfee last date kab hai",
    answerEn: "The fee is due on 15 November.",
    sourceTitle: "Fee Notice 2026-27",
    ...overrides,
  };
}

describe("validateKbForm", () => {
  it("builds a draft KBEntry from valid input", () => {
    const { errors, entry } = validateKbForm(valid({ tags: "fees, deadline", isFaq: true, validUntil: "2026-12-31", sourceRef: "p.1" }));
    expect(errors).toEqual({});
    expect(entry).toEqual({
      id: "FEE-012",
      department: "accounts",
      question_variants: ["When is the fee due?", "fee last date kab hai"],
      answer_en: "The fee is due on 15 November.",
      answer_hi: null,
      source_title: "Fee Notice 2026-27",
      source_ref: "p.1",
      valid_from: null,
      valid_until: "2026-12-31",
      tags: ["fees", "deadline"],
      is_faq: true,
      status: "draft",
    });
  });

  it("requires every mandatory field", () => {
    const { errors, entry } = validateKbForm(emptyFormValues());
    expect(entry).toBeNull();
    expect(Object.keys(errors).sort()).toEqual(["answerEn", "department", "id", "questionVariants", "sourceTitle"]);
  });

  it.each(["fee-012", "F-012", "FEEEE-012", "FEE-12", "FEE-12345", "FEE012", "FEE-01a"])("rejects id %s", (id) => {
    expect(validateKbForm(valid({ id })).errors.id).toMatch(/2-4 capital letters/);
  });

  it.each(["AB-123", "ABCD-1234", "FEE-012"])("accepts id %s", (id) => {
    expect(validateKbForm(valid({ id })).errors.id).toBeUndefined();
  });

  it("needs at least one non-blank question variant", () => {
    expect(validateKbForm(valid({ questionVariants: " \n  \n" })).errors.questionVariants).toBeTruthy();
    expect(validateKbForm(valid({ questionVariants: "one" })).errors.questionVariants).toBeUndefined();
  });

  it("validates dates and their order", () => {
    expect(validateKbForm(valid({ validFrom: "2026-13-01" })).errors.validFrom).toBeTruthy();
    expect(validateKbForm(valid({ validFrom: "2026-11-10", validUntil: "2026-11-01" })).errors.validUntil).toMatch(/before/);
    expect(validateKbForm(valid({ validFrom: "2026-11-01", validUntil: "2026-11-01" })).errors.validUntil).toBeUndefined();
  });

  it("round-trips an entry through the form values", () => {
    const entry = {
      id: "HOS-101",
      department: "hostel",
      question_variants: ["a", "b"] as [string, ...string[]],
      answer_en: "x",
      answer_hi: "हिंदी",
      source_title: "s",
      source_ref: "r",
      valid_from: "2026-01-01",
      valid_until: "2026-12-31",
      tags: ["t1", "t2"],
      is_faq: true,
      status: "approved" as const,
    };
    const back = validateKbForm(valuesFromEntry(entry)).entry;
    expect(back).toEqual({ ...entry, status: "draft" });
  });
});

describe("gap draft seed", () => {
  it("suggests an id prefix that matches the id pattern", () => {
    expect(suggestIdPrefix("transport")).toBe("TRA");
    expect(suggestIdPrefix("exam_cell")).toBe("EC");
    expect(suggestIdPrefix(null)).toBe("GEN");
    expect(suggestIdPrefix("x")).toBe("GEN");
    for (const d of ["accounts", "hostel", "exam_cell", "admissions", null]) {
      expect(suggestIdPrefix(d)).toMatch(/^[A-Z]{2,4}$/);
    }
  });

  it("builds a seed from a cluster (unique non-blank examples) and prefills the form", () => {
    const seed = buildDraftSeed({
      cluster_id: "gc-3",
      label: "Bus Noida",
      department: "transport",
      examples: ["bus kab aayegi", " ", "bus kab aayegi", "Noida bus timing"],
    });
    expect(seed).toMatchObject({ clusterId: "gc-3", department: "transport", idPrefix: "TRA" });
    expect(seed.questionVariants).toEqual(["bus kab aayegi", "Noida bus timing"]);
    const values = valuesFromSeed(seed);
    expect(values.department).toBe("transport");
    expect(values.questionVariants).toBe("bus kab aayegi\nNoida bus timing");
    expect(values.id).toBe("TRA-");
    expect(values.answerEn).toBe("");
  });

  it("reads router state defensively", () => {
    expect(readDraftSeed(null)).toBeNull();
    expect(readDraftSeed({})).toBeNull();
    expect(readDraftSeed({ [KB_DRAFT_STATE_KEY]: "nope" })).toBeNull();
    expect(readDraftSeed({ [KB_DRAFT_STATE_KEY]: { clusterId: 5 } })).toBeNull();
    const seed = readDraftSeed({ [KB_DRAFT_STATE_KEY]: { clusterId: "gc-1", questionVariants: ["q", 7], idPrefix: "bad" } });
    expect(seed).toMatchObject({ clusterId: "gc-1", questionVariants: ["q"], idPrefix: "GEN", department: null });
  });
});

import { describe, expect, it } from "vitest";
import {
  displayNumber,
  formatDateTime,
  formatDuration,
  formatRelative,
  formatTime,
  humanize,
  isMasked,
  maskNumber,
  parseApiDate,
  secondsBetween,
  startOfTodayIST,
} from "./format";
import { SLA_TARGET_MINUTES, slaFor } from "./sla";

const MASKED = "+91•••••0002";

describe("masking display", () => {
  it("masks like the API: first 3 + five bullets + last 4", () => {
    expect(maskNumber("+919876540002")).toBe(MASKED);
  });
  it("shows bullets only for numbers shorter than 8 characters, null for missing", () => {
    expect(maskNumber("1234567")).toBe("•••");
    expect(maskNumber("12345678")).toBe("123•••••5678");
    expect(maskNumber(null)).toBeNull();
    expect(maskNumber("")).toBeNull();
  });
  it("leaves an already masked value unchanged", () => {
    expect(maskNumber(MASKED)).toBe(MASKED);
    expect(isMasked(MASKED)).toBe(true);
    expect(isMasked("+919876540002")).toBe(false);
  });
  it("masking is idempotent: masking again, or displaying a masked value, never changes it (M8)", () => {
    for (const value of ["+91•••••0101", "+91•••••0002", "•••", "123•••••5678"]) {
      expect(maskNumber(value)).toBe(value);
      expect(maskNumber(maskNumber(value))).toBe(value);
      expect(displayNumber(value)).toBe(value);
      expect(displayNumber(value, true)).toBe(value);
    }
    expect(maskNumber(maskNumber("+910000000101"))).toBe("+91•••••0101");
    expect(displayNumber("112")).toBe("•••"); // callers treat public emergency numbers as plain text before masking
  });
  it("displayNumber never shows a full number unless revealed", () => {
    expect(displayNumber(MASKED)).toBe(MASKED);
    expect(displayNumber("+919876540002")).toBe(MASKED); // second line of defence
    expect(displayNumber("+919876540002", true)).toBe("+919876540002");
    expect(displayNumber(null)).toBe("—");
    expect(displayNumber(undefined, true)).toBe("—");
  });
});

describe("dates (Asia/Kolkata)", () => {
  it("formats an instant in IST regardless of the browser timezone", () => {
    expect(formatDateTime("2026-10-31T10:15:00+00:00")).toBe("31 Oct 2026, 15:45 IST");
    expect(formatTime("2026-10-31T18:30:00+00:00")).toBe("00:00");
    expect(formatTime("2026-10-31T10:15:07+00:00", true)).toBe("15:45:07");
  });
  it("treats an offset-less timestamp as UTC and handles bad input", () => {
    expect(parseApiDate("2026-10-31T10:15:00")?.toISOString()).toBe("2026-10-31T10:15:00.000Z");
    expect(parseApiDate("nope")).toBeNull();
    expect(parseApiDate(null)).toBeNull();
    expect(formatDateTime(null)).toBe("—");
  });
  it("startOfTodayIST is 18:30Z of the previous UTC day", () => {
    // 02:00 IST on 31 Oct = 20:30Z on 30 Oct -> IST day starts 30 Oct 18:30Z
    expect(startOfTodayIST(new Date("2026-10-30T20:30:00Z"))).toBe("2026-10-30T18:30:00.000Z");
    // 23:59 IST on 31 Oct = 18:29Z on 31 Oct -> same IST day
    expect(startOfTodayIST(new Date("2026-10-31T18:29:00Z"))).toBe("2026-10-30T18:30:00.000Z");
    // 00:00 IST on 1 Nov starts the next day
    expect(startOfTodayIST(new Date("2026-10-31T18:30:00Z"))).toBe("2026-10-31T18:30:00.000Z");
  });
});

describe("durations and relative time", () => {
  it("formats durations", () => {
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(185)).toBe("3m 05s");
    expect(formatDuration(3720)).toBe("1h 02m");
    expect(formatDuration(-5)).toBe("0s");
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(Number.NaN)).toBe("—");
  });
  it("secondsBetween never goes negative", () => {
    expect(secondsBetween("2026-10-31T10:00:00+00:00", "2026-10-31T10:01:30+00:00")).toBe(90);
    expect(secondsBetween("2026-10-31T10:05:00+00:00", "2026-10-31T10:00:00+00:00")).toBe(0);
    expect(secondsBetween(null, undefined)).toBe(0);
  });
  it("formatRelative", () => {
    const now = new Date("2026-10-31T12:00:00Z");
    expect(formatRelative("2026-10-31T11:59:40Z", now)).toBe("just now");
    expect(formatRelative("2026-10-31T11:55:00Z", now)).toBe("5m ago");
    expect(formatRelative("2026-10-31T09:00:00Z", now)).toBe("3h ago");
    expect(formatRelative("2026-10-28T12:00:00Z", now)).toBe("3d ago");
    expect(formatRelative("2026-10-31T12:00:30Z", now)).toBe("just now"); // clock skew
    expect(formatRelative(null, now)).toBe("—");
  });
  it("humanize", () => {
    expect(humanize("exam_cell")).toBe("Exam cell");
    expect(humanize(null)).toBe("—");
  });
});

describe("SLA targets", () => {
  it("has a target for every priority, tightest for P1", () => {
    expect(SLA_TARGET_MINUTES.P1).toBeLessThan(SLA_TARGET_MINUTES.P2);
    expect(SLA_TARGET_MINUTES.P2).toBeLessThan(SLA_TARGET_MINUTES.P3);
    expect(SLA_TARGET_MINUTES.P3).toBeLessThan(SLA_TARGET_MINUTES.P4);
  });
  it("moves ok -> warn (75%) -> breached", () => {
    expect(slaFor("P1", 60).state).toBe("ok");
    expect(slaFor("P1", 11 * 60).state).toBe("ok");
    expect(slaFor("P1", 12 * 60).state).toBe("warn");
    expect(slaFor("P1", 15 * 60).state).toBe("breached");
    const late = slaFor("P1", 18 * 60);
    expect(late.remainingSeconds).toBe(-180);
  });
});

import { ticketTypeLabel } from "./format";
describe("ticketTypeLabel", () => {
  it("makes SYSTEM_FAILURE readable and keeps unknown types as plain text", () => {
    expect(ticketTypeLabel("SYSTEM_FAILURE")).toBe("System failure");
    expect(ticketTypeLabel("KNOWLEDGE_GAP")).toBe("Knowledge gap");
    expect(ticketTypeLabel("SOMETHING_NEW")).toBe("Something new");
    expect(ticketTypeLabel(null)).toBe("—");
  });
});

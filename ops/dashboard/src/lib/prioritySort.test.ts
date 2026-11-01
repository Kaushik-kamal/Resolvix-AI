import { describe, expect, it } from "vitest";
import { comparePriority, groupByPriority, priorityRank, prioritySort } from "./prioritySort";

const t = (id: string, priority: string | null, created_at: string) => ({ id, priority, created_at });

describe("prioritySort", () => {
  it("sorts P1 -> P4, then newest first within a priority", () => {
    const items = [
      t("a", "P3", "2026-10-31T10:00:00+00:00"),
      t("b", "P1", "2026-10-31T09:00:00+00:00"),
      t("c", "P1", "2026-10-31T11:00:00+00:00"),
      t("d", "P4", "2026-10-31T12:00:00+00:00"),
      t("e", "P2", "2026-10-31T08:00:00+00:00"),
      t("f", "P3", "2026-10-31T10:30:00+00:00"),
    ];
    expect(prioritySort(items).map((x) => x.id)).toEqual(["c", "b", "e", "f", "a", "d"]);
  });

  it("does not mutate its input", () => {
    const items = [t("a", "P4", "2026-10-31T10:00:00+00:00"), t("b", "P1", "2026-10-31T10:00:00+00:00")];
    const copy = [...items];
    prioritySort(items);
    expect(items).toEqual(copy);
  });

  it("compares instants, not strings (different offsets)", () => {
    // 10:00+05:30 is 04:30Z, which is OLDER than 05:00Z although the string sorts higher
    const older = t("older", "P2", "2026-10-31T10:00:00+05:30");
    const newer = t("newer", "P2", "2026-10-31T05:00:00+00:00");
    expect(prioritySort([older, newer]).map((x) => x.id)).toEqual(["newer", "older"]);
  });

  it("puts unknown or missing priorities last and keeps equal items stable", () => {
    const items = [
      t("x", null, "2026-10-31T10:00:00+00:00"),
      t("y", "P4", "2026-10-31T10:00:00+00:00"),
      t("s1", "P2", "2026-10-31T10:00:00+00:00"),
      t("s2", "P2", "2026-10-31T10:00:00+00:00"),
    ];
    expect(prioritySort(items).map((i) => i.id)).toEqual(["s1", "s2", "y", "x"]);
  });

  it("treats naive timestamps as UTC and bad ones as oldest", () => {
    const a = t("a", "P1", "2026-10-31T10:00:00");
    const b = t("b", "P1", "garbage");
    expect(comparePriority(a, b)).toBeLessThan(0);
  });

  it("priorityRank and groupByPriority", () => {
    expect(["P1", "P2", "P3", "P4", "P9", null].map(priorityRank)).toEqual([0, 1, 2, 3, 4, 4]);
    const groups = groupByPriority([
      t("a", "P1", "2026-10-31T10:00:00+00:00"),
      t("b", "P1", "2026-10-31T11:00:00+00:00"),
      t("c", "P3", "2026-10-31T11:00:00+00:00"),
    ]);
    expect(groups.P1.map((x) => x.id)).toEqual(["b", "a"]);
    expect(groups.P2).toEqual([]);
    expect(groups.P3).toHaveLength(1);
  });
});

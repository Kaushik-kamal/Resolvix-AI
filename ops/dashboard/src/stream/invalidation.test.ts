import { describe, expect, it } from "vitest";
import { qk } from "../api/queryKeys";
import { invalidationsFor, invalidationsOnReconnect } from "./invalidation";

describe("SSE query invalidation", () => {
  it("call.turn refreshes call lists but never call detail (detail GET is audited)", () => {
    const keys = invalidationsFor("call.turn", { call_id: "c1" } as never);
    expect(keys).toEqual([qk.calls.lists()]);
  });
  it("call.ended refreshes lists and that call's detail", () => {
    const keys = invalidationsFor("call.ended", { call_id: "c1" } as never);
    expect(keys).toEqual([qk.calls.lists(), qk.calls.detailAny("c1")]);
  });
  it("ticket.created and alert.p1 refresh ticket lists", () => {
    expect(invalidationsFor("ticket.created", {} as never)).toEqual([qk.tickets.lists()]);
    expect(invalidationsFor("alert.p1", {} as never)).toEqual([qk.tickets.lists()]);
  });
  it("ticket.updated refreshes lists, detail and events of that ticket", () => {
    const keys = invalidationsFor("ticket.updated", { ticket_id: "EX-1001" } as never);
    expect(keys).toEqual([qk.tickets.lists(), qk.tickets.detailAny("EX-1001"), qk.tickets.events("EX-1001")]);
  });
  it("gap.created refreshes gaps; reconnect refreshes everything live", () => {
    expect(invalidationsFor("gap.created", {} as never)).toEqual([qk.gaps.all]);
    expect(invalidationsOnReconnect()).toEqual([qk.calls.all, qk.tickets.all, qk.gaps.all]);
  });
  it("detail keys are prefixed by detailAny so a prefix invalidation matches", () => {
    expect(qk.tickets.detail("EX-1001", true).slice(0, 3)).toEqual(qk.tickets.detailAny("EX-1001"));
    expect(qk.calls.detail("c1").slice(0, 3)).toEqual(qk.calls.detailAny("c1"));
  });
});

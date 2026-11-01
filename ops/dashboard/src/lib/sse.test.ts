import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource, FakeEventSourceCtor } from "../test/fakeEventSource";
import { backoffDelay, createEventStreamClient, type StreamState } from "./sse";

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.reset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("backoffDelay", () => {
  it("doubles from 1 s and caps at 30 s", () => {
    expect([1, 2, 3, 4, 5, 6, 7, 8].map((n) => backoffDelay(n))).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
  });
  it("honours custom options and clamps attempt below 1", () => {
    expect(backoffDelay(0, { baseMs: 500 })).toBe(500);
    expect(backoffDelay(3, { baseMs: 100, factor: 3, maxMs: 500 })).toBe(500);
  });
});

function setup(extra: Partial<Parameters<typeof createEventStreamClient>[0]> = {}) {
  const events: [string, unknown][] = [];
  const states: StreamState[] = [];
  const opens: boolean[] = [];
  const client = createEventStreamClient({
    url: "/v1/stream",
    EventSourceImpl: FakeEventSourceCtor,
    onEvent: (name, data) => events.push([name, data]),
    onState: (s) => states.push(s),
    onOpen: (re) => opens.push(re),
    ...extra,
  });
  return { client, events, states, opens };
}

describe("createEventStreamClient", () => {
  it("connects with credentials and reports open", () => {
    const { client, states, opens } = setup();
    client.start();
    const es = FakeEventSource.last();
    expect(es.url).toBe("/v1/stream");
    expect(es.init?.withCredentials).toBe(true);
    es.open();
    expect(client.getState().status).toBe("open");
    expect(states.at(-1)?.status).toBe("open");
    expect(opens).toEqual([false]);
    client.close();
  });

  it("parses named events and ignores malformed data lines", () => {
    const onParseError = vi.fn();
    const { client, events } = setup({ onParseError });
    client.start();
    const es = FakeEventSource.last();
    es.open();
    es.emit("ticket.created", { ticket_id: "EX-1001", priority: "P1" });
    es.emit("call.turn", "{not json");
    es.emit("alert.p1", { ticket_id: "EX-1001" });
    expect(events).toEqual([
      ["ticket.created", { ticket_id: "EX-1001", priority: "P1" }],
      ["alert.p1", { ticket_id: "EX-1001" }],
    ]);
    expect(onParseError).toHaveBeenCalledWith("call.turn", "{not json");
    client.close();
  });

  it("reconnects with exponential backoff after errors and resets after a successful open", () => {
    const { client, states } = setup();
    client.start();
    FakeEventSource.last().fail();
    expect(client.getState()).toMatchObject({ status: "reconnecting", attempt: 1, retryInMs: 1000 });
    expect(FakeEventSource.instances).toHaveLength(1);

    vi.advanceTimersByTime(999);
    expect(FakeEventSource.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeEventSource.instances).toHaveLength(2);

    FakeEventSource.last().fail();
    expect(client.getState()).toMatchObject({ attempt: 2, retryInMs: 2000 });
    vi.advanceTimersByTime(2000);
    FakeEventSource.last().fail();
    expect(client.getState()).toMatchObject({ attempt: 3, retryInMs: 4000 });
    vi.advanceTimersByTime(4000);

    FakeEventSource.last().open();
    expect(client.getState()).toMatchObject({ status: "open", attempt: 0, retryInMs: null });

    FakeEventSource.last().fail();
    expect(client.getState()).toMatchObject({ attempt: 1, retryInMs: 1000 }); // reset after the successful open
    expect(states.some((s) => s.status === "reconnecting")).toBe(true);
    client.close();
  });

  it("closes the failed source and tells the caller about a RE-connect (not the first open)", () => {
    const { client, opens } = setup();
    client.start();
    const first = FakeEventSource.last();
    first.open();
    first.fail();
    expect(first.closed).toBe(true);
    vi.advanceTimersByTime(1000);
    FakeEventSource.last().open();
    expect(opens).toEqual([false, true]);
    client.close();
  });

  it("caps the delay at 30 s", () => {
    const { client } = setup();
    client.start();
    for (let i = 0; i < 8; i++) {
      FakeEventSource.last().fail();
      vi.advanceTimersByTime(30_000);
    }
    FakeEventSource.last().fail();
    expect(client.getState().retryInMs).toBe(30_000);
    client.close();
  });

  it("close() stops events, cancels a pending reconnect and does not reconnect later", () => {
    const { client, events } = setup();
    client.start();
    const es = FakeEventSource.last();
    es.open();
    es.fail();
    client.close();
    vi.advanceTimersByTime(60_000);
    expect(FakeEventSource.instances).toHaveLength(1);
    es.emit("ticket.created", { ticket_id: "X" });
    expect(events).toEqual([]);
    expect(client.getState().status).toBe("closed");
  });

  it("ignores events from a source that was already replaced", () => {
    const { client, events } = setup();
    client.start();
    const old = FakeEventSource.last();
    old.open();
    old.fail();
    vi.advanceTimersByTime(1000);
    old.emit("ticket.created", { ticket_id: "STALE" });
    FakeEventSource.last().open();
    FakeEventSource.last().emit("ticket.created", { ticket_id: "FRESH" });
    expect(events).toEqual([["ticket.created", { ticket_id: "FRESH" }]]);
    client.close();
  });

  it("start() is idempotent and a missing EventSource ends in closed", () => {
    const { client } = setup();
    client.start();
    client.start();
    expect(FakeEventSource.instances).toHaveLength(1);
    client.close();

    const states: StreamState[] = [];
    const none = createEventStreamClient({ url: "/x", EventSourceImpl: undefined, onState: (s) => states.push(s) });
    const original = (globalThis as { EventSource?: unknown }).EventSource;
    (globalThis as { EventSource?: unknown }).EventSource = undefined;
    none.start();
    (globalThis as { EventSource?: unknown }).EventSource = original;
    expect(none.getState().status).toBe("closed");
  });
});

// Waking services, with fake timers and a fake fetch: no network, no waiting.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bannerView, TRY_AGAIN, WAKING_TEXT } from "./banner.js";
import { classifyResponse, EARMARK_ERROR, Outcome, retryAfterSeconds } from "./classify.js";
import { createClient } from "./client.js";
import { ApiError, Cancelled, UNCONFIRMED, UNREACHABLE } from "./errors.js";
import { TIMING } from "./timing.js";
import { backoffMs, HEALTH_PATH } from "./waker.js";

const ORIGIN = "https://donations.example";
const HEALTH = ORIGIN + HEALTH_PATH;
const URL = ORIGIN + "/api/donations/impact";

const json = (status, body, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const NETWORK = "network"; // fetch rejects, as when nothing answers
const HANG = "hang"; // fetch never settles until aborted

// A fetch that answers each URL from its own queue (the last answer repeats)
// and records every call.
function fakeFetch(routes) {
  const calls = [];
  const fetch = (url, init = {}) => {
    calls.push({ url, method: init.method ?? "GET" });
    const queue = routes[url];
    if (!queue) throw new Error(`unexpected request to ${url}`);
    const next = queue.length > 1 ? queue.shift() : queue[0];
    if (next === NETWORK) return Promise.reject(new TypeError("Failed to fetch"));
    if (next === HANG)
      return new Promise((_, reject) =>
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
      );
    return Promise.resolve(typeof next === "function" ? next() : next);
  };
  return { fetch, calls, count: (url, method = "GET") => calls.filter((c) => c.url === url && c.method === method).length };
}

function setup(routes) {
  const fake = fakeFetch(routes);
  const client = createClient({ fetch: fake.fetch, now: () => Date.now(), random: () => 1 });
  const states = [];
  client.waker.subscribe(() => states.push(client.waker.getSnapshot()));
  return { ...fake, client, states };
}

const get = (client, url = URL, origin = ORIGIN) => client.send({ origin, url, idempotent: true });
const post = (client, url = ORIGIN + "/api/donations", origin = ORIGIN) =>
  client.send({ origin, url, init: { method: "POST", body: "{}" }, idempotent: false });

// Settles a promise while advancing fake time, and reports how it ended.
async function settle(promise, ms = TIMING.WAKE_DEADLINE_MS + 10_000) {
  const outcome = promise.then(
    (value) => ({ value }),
    (error) => ({ error }),
  );
  await vi.advanceTimersByTimeAsync(ms);
  return outcome;
}

beforeEach(() => vi.useFakeTimers({ now: 1_000_000 }));
afterEach(() => vi.useRealTimers());

describe("classifying failures", () => {
  it.each([
    [200, {}, Outcome.OK],
    [429, { error: "rate_limited" }, Outcome.RATE_LIMITED],
    [502, null, Outcome.WAKING],
    [503, "<html>starting</html>", Outcome.WAKING],
    [504, [], Outcome.WAKING],
    [503, { error: EARMARK_ERROR, detail: "Could not check..." }, Outcome.EARMARK],
    [503, { error: "payments_unavailable" }, Outcome.FAILED], // the app's own 503: final
    [503, { error: "admin_disabled" }, Outcome.FAILED],
    [500, { error: "internal_server_error" }, Outcome.FAILED],
    [401, { error: "unauthorised" }, Outcome.FAILED],
    [404, { error: "not_found" }, Outcome.FAILED],
  ])("status %i with %j is %s", (status, body, expected) => {
    expect(classifyResponse(status, body)).toBe(expected);
  });

  it("reads Retry-After as whole seconds only", () => {
    expect(retryAfterSeconds(new Headers({ "Retry-After": "12" }))).toBe(12);
    expect(retryAfterSeconds(new Headers({ "Retry-After": "soon" }))).toBeNull();
    expect(retryAfterSeconds(new Headers())).toBeNull();
  });

  it("backs off exponentially with jitter, capped", () => {
    const max = (n) => backoffMs(n, TIMING, () => 1);
    const min = (n) => backoffMs(n, TIMING, () => 0);
    expect([max(0), max(1), max(2)]).toEqual([500, 1000, 2000]);
    expect(max(10)).toBe(TIMING.BACKOFF_MAX_MS);
    expect(min(10)).toBe(TIMING.BACKOFF_MAX_MS / 2);
  });
});

describe("a GET while the service wakes", () => {
  it("waits for the health check, then retries and carries on", async () => {
    const t = setup({ [URL]: [NETWORK, json(200, { total: 1 })], [HEALTH]: [json(503, { status: "error" }), json(200, {})] });
    const { value } = await settle(get(t.client));
    expect(value).toEqual({ total: 1 });
    expect(t.count(HEALTH)).toBe(2);
    expect(t.states.map((s) => s.waking)).toEqual([1, 0]); // banner on, then off
    expect(t.client.waker.getSnapshot().failed).toBe(false);
  });

  it("treats Azure's own 503 and an unanswered attempt as waking", async () => {
    const t = setup({ [URL]: [json(503, null), HANG, json(200, { ok: true })], [HEALTH]: [json(200, {})] });
    const { value } = await settle(get(t.client));
    expect(value).toEqual({ ok: true });
    expect(t.count(URL)).toBe(3);
  });

  it("gives up at the deadline and says the server could not be reached", async () => {
    const t = setup({ [URL]: [NETWORK], [HEALTH]: [NETWORK] });
    const started = Date.now();
    const { error } = await settle(get(t.client));
    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.code, error.message]).toEqual([0, "network_error", UNREACHABLE]);
    expect(Date.now() - started).toBeLessThanOrEqual(TIMING.WAKE_DEADLINE_MS + TIMING.ATTEMPT_TIMEOUT_MS);
    expect(t.client.waker.getSnapshot()).toMatchObject({ waking: 0, failed: true });
  });

  it("shares one wake loop and one banner between requests to the same service", async () => {
    const other = ORIGIN + "/api/donations/offline-methods";
    const t = setup({
      [URL]: [NETWORK, json(200, { a: 1 })],
      [other]: [NETWORK, json(200, { b: 2 })],
      [HEALTH]: [json(503, {}), json(503, {}), json(200, {})],
    });
    const both = Promise.all([get(t.client), get(t.client, other)]);
    const { value } = await settle(both);
    expect(value).toEqual([{ a: 1 }, { b: 2 }]);
    expect(t.count(HEALTH)).toBe(3); // one loop, not one per request
    expect(Math.max(...t.states.map((s) => s.waking))).toBe(1);
  });

  it("stops waiting when the visitor leaves the page", async () => {
    const t = setup({ [URL]: [NETWORK], [HEALTH]: [NETWORK] });
    const leave = new AbortController();
    const pending = t.client.withSignal(leave.signal, () => get(t.client));
    await vi.advanceTimersByTimeAsync(2_000);
    leave.abort();
    const { error } = await settle(pending, 1_000);
    expect(error).toBeInstanceOf(Cancelled);
    const callsAtLeaving = t.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(t.calls.length).toBe(callsAtLeaving); // nothing keeps polling for nobody
    expect(t.client.waker.getSnapshot().waking).toBe(0);
  });

  it("retries without a health check when the service has no address of its own", async () => {
    const t = setup({ "/api/animals": [NETWORK, json(200, { animals: [] })] });
    const { value } = await settle(get(t.client, "/api/animals", ""));
    expect(value).toEqual({ animals: [] });
    expect(t.calls.every((c) => c.url === "/api/animals")).toBe(true);
  });
});

describe("answers that are never retried", () => {
  it("shows a wrong staff password exactly as before", async () => {
    const t = setup({ [URL]: [json(401, { error: "unauthorised" })] });
    const { error } = await settle(get(t.client));
    expect([error.status, error.code]).toEqual([401, "unauthorised"]);
    expect(t.count(URL)).toBe(1);
  });

  it("says how long to wait after a 429, without retrying", async () => {
    const t = setup({ [URL]: [json(429, { error: "rate_limited" }, { "Retry-After": "42" })] });
    const { error } = await settle(get(t.client));
    expect([error.status, error.message]).toEqual([429, "Too many requests. Please try again in 42 seconds."]);
    expect(t.count(URL)).toBe(1);
  });

  it("does not retry a server error", async () => {
    const t = setup({ [URL]: [json(500, { error: "internal_server_error" })] });
    const { error } = await settle(get(t.client));
    expect(error.status).toBe(500);
    expect(t.count(URL)).toBe(1);
  });
});

describe("a POST may change data, so it is sent once", () => {
  const SEND = ORIGIN + "/api/donations";

  it("wakes a quiet service first, then sends once", async () => {
    const t = setup({ [HEALTH]: [NETWORK, json(200, {})], [SEND]: [json(201, { id: 9 })] });
    const { value } = await settle(post(t.client));
    expect(value).toEqual({ id: 9 });
    expect(t.calls.map((c) => c.method + " " + c.url)).toEqual([`GET ${HEALTH}`, `GET ${HEALTH}`, `POST ${SEND}`]);
  });

  it("does not wake a service that answered recently", async () => {
    const t = setup({ [URL]: [json(200, {})], [SEND]: [json(201, { id: 9 })] });
    await settle(get(t.client));
    await settle(post(t.client));
    expect(t.count(HEALTH)).toBe(0);
  });

  it.each([[NETWORK], [HANG], [json(502, null)]])("never resends after an unclear failure (%s)", async (failure) => {
    const t = setup({ [HEALTH]: [json(200, {})], [SEND]: [failure, json(201, { id: 9 })] });
    const { error } = await settle(post(t.client));
    expect([error.code, error.message]).toEqual(["unconfirmed", UNCONFIRMED]);
    expect(t.count(SEND, "POST")).toBe(1);
  });

  it("tries the earmark answer at most three times, then offers Try again", async () => {
    const earmark = () => json(503, { error: EARMARK_ERROR, detail: "Could not check the earmarked animal right now." });
    const t = setup({ [HEALTH]: [json(200, {})], [SEND]: [earmark] });
    const { error } = await settle(post(t.client));
    expect(t.count(SEND, "POST")).toBe(TIMING.EARMARK_MAX_TRIES);
    expect([error.status, error.retryable, error.message]).toEqual([503, true, "Could not check the earmarked animal right now."]);
  });

  it("spaces earmark tries by Retry-After, within the cap", async () => {
    const earmark = () => json(503, { error: EARMARK_ERROR }, { "Retry-After": "60" });
    const t = setup({ [HEALTH]: [json(200, {})], [SEND]: [earmark, json(201, { id: 3 })] });
    const pending = post(t.client);
    await vi.advanceTimersByTimeAsync(100);
    expect(t.count(SEND, "POST")).toBe(1);
    await vi.advanceTimersByTimeAsync(TIMING.EARMARK_MAX_WAIT_MS - 500);
    expect(t.count(SEND, "POST")).toBe(1); // 60 s asked, capped at 20 s: not yet
    const { value } = await settle(pending, 1_000);
    expect(value).toEqual({ id: 3 });
    expect(t.count(SEND, "POST")).toBe(2);
  });

  it("is sent once, without waking, on this same site", async () => {
    const t = setup({ "/api/enquiries": [NETWORK] });
    const { error } = await settle(post(t.client, "/api/enquiries", ""));
    expect(error.code).toBe("unconfirmed");
    expect(t.calls).toHaveLength(1);
  });
});

describe("the banner", () => {
  it("is hidden, waking, or failed with a Try again button", () => {
    expect(bannerView({ waking: 0, failed: false }).visible).toBe(false);
    expect(bannerView({ waking: 2, failed: false })).toMatchObject({ visible: true, text: WAKING_TEXT, action: null });
    expect(bannerView({ waking: 0, failed: true })).toMatchObject({ visible: true, text: UNREACHABLE, action: TRY_AGAIN });
    expect(bannerView({ waking: 1, failed: true }).text).toBe(WAKING_TEXT); // trying again wins
  });

  it("Try again clears the failure and asks pages to reload", async () => {
    const t = setup({ [URL]: [NETWORK], [HEALTH]: [NETWORK] });
    await settle(get(t.client));
    expect(t.client.waker.getSnapshot()).toMatchObject({ failed: true, retryToken: 0 });
    t.client.waker.retry();
    expect(t.client.waker.getSnapshot()).toMatchObject({ failed: false, retryToken: 1 });
  });

  it("clears the failure once a service answers again", async () => {
    const t = setup({ [URL]: [NETWORK, json(200, {})], [HEALTH]: [NETWORK] });
    await settle(get(t.client));
    expect(t.client.waker.getSnapshot().failed).toBe(true);
    await settle(get(t.client));
    expect(t.client.waker.getSnapshot().failed).toBe(false);
  });
});

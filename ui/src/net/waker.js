// Waking a service that has scaled to zero, once per service however many
// requests are waiting on it, and the state the banner shows.
import { ApiError, Cancelled, UNREACHABLE } from "./errors.js";

// Each service's own health check: public, never rate limited, and it answers
// 200 only once the service can use its database (services/*/app.py).
export const HEALTH_PATH = "/health";

export function backoffMs(attempt, timing, random) {
  const ceiling = Math.min(timing.BACKOFF_MAX_MS, timing.BACKOFF_FIRST_MS * 2 ** attempt);
  // "Equal jitter": at least half the wait, plus a random part of the rest.
  return ceiling / 2 + random() * (ceiling / 2);
}

// Waits ms, or stops early with Cancelled if the signal fires.
export function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Cancelled());
    const timer = setTimeout(done, ms);
    function done() {
      signal?.removeEventListener("abort", stop);
      resolve();
    }
    function stop() {
      clearTimeout(timer);
      reject(new Cancelled());
    }
    signal?.addEventListener("abort", stop, { once: true });
  });
}

// One request with its own time limit. Returns what came back, or
// { noAnswer: true } if nothing did in time. Throws Cancelled only if the
// caller's signal fired.
export async function attempt(fetchImpl, url, init, timeoutMs, signal) {
  if (signal?.aborted) throw new Cancelled();
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(cancel, timeoutMs);
  try {
    const response = await fetchImpl(url, { ...init, signal: controller.signal });
    const body = await response.json().catch(() => null);
    return { status: response.status, headers: response.headers, body };
  } catch {
    if (signal?.aborted) throw new Cancelled();
    return { noAnswer: true };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

export function createWaker({ fetch: fetchImpl, now, random, timing }) {
  const loops = new Map(); // origin -> { controller, waiters, promise }
  const lastAwake = new Map(); // origin -> time of its last answer
  const listeners = new Set();
  let snapshot = Object.freeze({ waking: 0, failed: false, retryToken: 0 });

  function update(change) {
    snapshot = Object.freeze({ ...snapshot, ...change });
    listeners.forEach((listener) => listener());
  }

  function markAwake(origin) {
    lastAwake.set(origin, now());
    if (snapshot.failed) update({ failed: false });
  }

  function recentlyAwake(origin) {
    const at = lastAwake.get(origin);
    return at !== undefined && now() - at < timing.RECENTLY_AWAKE_MS;
  }

  function fail() {
    update({ failed: true });
    return new ApiError(0, "network_error", UNREACHABLE);
  }

  // Poll the service's health until it answers 200, or give up at the
  // deadline. Without a separate address (local development behind Vite's
  // proxy) there is no health check to poll: one pause, and the caller tries
  // its own request again.
  async function run(origin, deadline, signal) {
    for (let n = 0; ; n += 1) {
      if (origin) {
        const result = await attempt(fetchImpl, origin + HEALTH_PATH, {}, timing.ATTEMPT_TIMEOUT_MS, signal);
        if (result.status === 200) {
          markAwake(origin);
          return;
        }
      } else if (n > 0) {
        return;
      }
      const wait = backoffMs(n, timing, random);
      if (now() + wait >= deadline) throw fail();
      await sleep(wait, signal);
    }
  }

  // Wait until `origin` is awake. Every caller waiting on the same service
  // shares one loop (single flight); the loop stops if all of them give up.
  function wake(origin, deadline, signal) {
    let loop = loops.get(origin);
    if (!loop) {
      const controller = new AbortController();
      loop = { controller, waiters: 0 };
      loop.promise = run(origin, deadline, controller.signal).finally(() => {
        loops.delete(origin);
        update({ waking: snapshot.waking - 1 });
      });
      loop.promise.catch(() => {}); // each waiter handles the outcome itself
      loops.set(origin, loop);
      update({ waking: snapshot.waking + 1 });
    }
    const shared = loop;
    shared.waiters += 1;
    return new Promise((resolve, reject) => {
      const leave = () => {
        shared.waiters -= 1;
        if (shared.waiters === 0) shared.controller.abort();
        reject(new Cancelled());
      };
      if (signal?.aborted) return leave();
      signal?.addEventListener("abort", leave, { once: true });
      shared.promise.then(
        (value) => {
          signal?.removeEventListener("abort", leave);
          resolve(value);
        },
        (error) => {
          signal?.removeEventListener("abort", leave);
          reject(error);
        },
      );
    });
  }

  return {
    wake,
    markAwake,
    recentlyAwake,
    fail,
    // "Try again" after giving up: clear the failure and ask every page that
    // loads data to load it again.
    retry: () => update({ failed: false, retryToken: snapshot.retryToken + 1 }),
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
  };
}

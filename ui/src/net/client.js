// Every request the website makes goes through send() (api.js), so waking a
// sleeping service and deciding what may be retried happen in one place.
//
// - A GET is safe to repeat: while the system is waking, it waits for the
//   service and tries again, until the deadline.
// - A POST or PUT may change data, and a request that timed out may still have
//   arrived. So it is never repeated after an unclear failure: if its service
//   has not answered recently, the service is woken first (by its health
//   check), then the request is sent once.
// - The one exception is the donations service's earmark answer, which comes
//   before anything is written (timing.js), tried up to EARMARK_MAX_TRIES.
import { Outcome, classifyResponse, retryAfterSeconds } from "./classify.js";
import { ApiError, UNCONFIRMED } from "./errors.js";
import { TIMING } from "./timing.js";
import { attempt, createWaker, sleep } from "./waker.js";

export function createClient({ fetch: fetchImpl, now = Date.now, random = Math.random, timing = TIMING }) {
  const waker = createWaker({ fetch: fetchImpl, now, random, timing });
  // The cancel signal of the page whose data is being loaded (withSignal).
  let ambientSignal;

  function answer(result, outcome) {
    const { status, headers, body } = result;
    if (outcome === Outcome.OK) return body;
    if (outcome === Outcome.RATE_LIMITED) {
      const seconds = retryAfterSeconds(headers);
      const message = seconds
        ? `Too many requests. Please try again in ${seconds} seconds.`
        : (body?.detail ?? "Too many requests. Please try again later.");
      throw new ApiError(429, "rate_limited", message);
    }
    throw new ApiError(status, body?.error ?? "error", body?.detail ?? `Something went wrong (${status}).`, {
      retryable: outcome === Outcome.EARMARK,
    });
  }

  async function fetchWithWake(origin, url, init, signal) {
    const deadline = now() + timing.WAKE_DEADLINE_MS;
    for (;;) {
      const result = await attempt(fetchImpl, url, init, timing.ATTEMPT_TIMEOUT_MS, signal);
      const outcome = result.noAnswer ? Outcome.WAKING : classifyResponse(result.status, result.body);
      if (outcome !== Outcome.WAKING) {
        waker.markAwake(origin);
        return answer(result, outcome);
      }
      if (now() >= deadline) throw waker.fail();
      await waker.wake(origin, deadline, signal);
    }
  }

  async function sendOnce(origin, url, init, signal, unconfirmed) {
    if (origin && !waker.recentlyAwake(origin)) {
      await waker.wake(origin, now() + timing.WAKE_DEADLINE_MS, signal);
    }
    for (let tries = 1; ; tries += 1) {
      // No cancel signal here: leaving the page must not cut off a request
      // that is already on its way, or nobody would know whether it arrived.
      const result = await attempt(fetchImpl, url, init, timing.SEND_TIMEOUT_MS);
      const outcome = result.noAnswer ? Outcome.WAKING : classifyResponse(result.status, result.body);
      if (outcome === Outcome.WAKING) throw new ApiError(0, "unconfirmed", unconfirmed);
      waker.markAwake(origin);
      if (outcome === Outcome.EARMARK && tries < timing.EARMARK_MAX_TRIES) {
        const seconds = retryAfterSeconds(result.headers);
        const wait = seconds === null ? timing.EARMARK_DEFAULT_WAIT_MS : seconds * 1000;
        await sleep(Math.min(wait, timing.EARMARK_MAX_WAIT_MS));
        continue;
      }
      return answer(result, outcome);
    }
  }

  return {
    // origin: the service's address ("" for this same site); idempotent: true
    // for GET. Must be called synchronously inside withSignal to be cancelled.
    send({ origin = "", url, init = {}, idempotent, unconfirmed = UNCONFIRMED }) {
      const signal = ambientSignal;
      return idempotent
        ? fetchWithWake(origin, url, init, signal)
        : sendOnce(origin, url, init, signal, unconfirmed);
    },
    // Runs load() with this cancel signal attached to every request it starts
    // synchronously, so a page can stop its waiting when the visitor leaves.
    withSignal(signal, load) {
      const previous = ambientSignal;
      ambientSignal = signal;
      try {
        return load();
      } finally {
        ambientSignal = previous;
      }
    },
    waker,
  };
}

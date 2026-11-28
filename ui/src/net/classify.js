// What a failed request means, so only the right failures are retried.

export const Outcome = Object.freeze({
  OK: "ok",
  // The system is starting up: no answer, or Azure's own 502/503/504.
  WAKING: "waking",
  // The donations service's own "could not check the earmarked animal" 503.
  EARMARK: "earmark",
  RATE_LIMITED: "rate_limited",
  // Anything else: a real answer that trying again would not change.
  FAILED: "failed",
});

// The donations service answers 503 with this error when it cannot reach the
// animals service (donations/routes.py, animals_unavailable).
export const EARMARK_ERROR = "animals_unavailable";

const PLATFORM_STATUSES = new Set([502, 503, 504]);

// Every answer our services write is a JSON object with a string `error`. Azure's
// ingress, answering for an app that is not up yet, writes something else, and
// sends no CORS header, so the browser usually sees no answer at all (a
// network error) rather than its status.
export function isServiceAnswer(body) {
  return body !== null && typeof body === "object" && !Array.isArray(body) && typeof body.error === "string";
}

export function classifyResponse(status, body) {
  if (status >= 200 && status < 300) return Outcome.OK;
  if (status === 429) return Outcome.RATE_LIMITED;
  if (PLATFORM_STATUSES.has(status)) {
    if (!isServiceAnswer(body)) return Outcome.WAKING;
    return body.error === EARMARK_ERROR ? Outcome.EARMARK : Outcome.FAILED;
  }
  return Outcome.FAILED;
}

// Seconds from a Retry-After header, or null if it is missing or not a whole
// number of seconds (the HTTP-date form is not used by our services).
export function retryAfterSeconds(headers) {
  const raw = headers?.get?.("Retry-After");
  if (!raw || !/^\d+$/.test(raw.trim())) return null;
  return Number(raw.trim());
}

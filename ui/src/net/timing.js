// Every number behind waking the services up, in one place (brief section 7.5).
//
// The services scale to zero when idle. The first request after a quiet spell
// waits while Azure starts a container and its database resumes: 47 seconds was
// the worst measured on this site (docs/evidence). These settings decide how
// long the website keeps trying before it gives up and says so.

// The whole wait, from the first failure to giving up.
export const WAKE_DEADLINE_MS = 90_000;

// One request. Azure holds a request while it starts the app, so this is
// generous; a request still unanswered after it is abandoned and tried again.
export const ATTEMPT_TIMEOUT_MS = 15_000;

// The single send of a form after its service has been woken. Longer, because
// it is never repeated: abandoning it early would only make the outcome unknown.
export const SEND_TIMEOUT_MS = 30_000;

// Waits between tries: doubling from the first, never above the cap, each
// shortened by a random part (jitter) so many visitors do not retry in step.
export const BACKOFF_FIRST_MS = 500;
export const BACKOFF_MAX_MS = 5_000;

// A service that answered this recently is taken to be awake: a form is sent to
// it straight away, without polling its health first.
export const RECENTLY_AWAKE_MS = 5 * 60_000;

// "Could not check the earmarked animal right now" (donations, 503): the
// animals service is waking. The donation is refused before anything is written
// (donations/service.py, record), so trying again cannot record it twice.
export const EARMARK_MAX_TRIES = 3;
// Between those tries: the server's Retry-After if it sends one, within the cap.
export const EARMARK_DEFAULT_WAIT_MS = 5_000;
export const EARMARK_MAX_WAIT_MS = 20_000;

export const TIMING = Object.freeze({
  WAKE_DEADLINE_MS,
  ATTEMPT_TIMEOUT_MS,
  SEND_TIMEOUT_MS,
  BACKOFF_FIRST_MS,
  BACKOFF_MAX_MS,
  RECENTLY_AWAKE_MS,
  EARMARK_MAX_TRIES,
  EARMARK_DEFAULT_WAIT_MS,
  EARMARK_MAX_WAIT_MS,
});

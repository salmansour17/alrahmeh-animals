# AI Usage Log

One row per meaningful interaction. Routine mechanics so shell syntax errors,
"what's next", and reformatting a command are not logged; only interactions that
changed a decision or produced code.

Standing architectural constraints referenced below live in `CLAUDE.md` in this
repository and predate the code they govern: Flask with the standard library's
`sqlite3` and no ORM, a repository layer as the only code permitted to touch
SQL, dependency injection at the composition root, no domain logic inside route
handlers, and design patterns applied only where they genuinely fit.

The final column of each row is written by me. Where an explanation runs longer
than a table cell holds legibly, it is kept in full in the numbered section of
the same number below the table.

| Date/commit | Tool | Prompt | Disposition | What changed & why (if modified) | In my own words, how this works |
|---|---|---|---|---|---|
| 2026-09-25 (planning, no commit) | Claude Code (Opus 5) | Asked for a commit and branching plan against the assignment's cadence requirements: 12+ commits over 6+ calendar days with no day exceeding 40%, every feature on its own branch merged by pull request. | Accepted | No code. Produced the 10-day schedule, the branch-per-feature layout, and the decision to keep each domain branch open across two days so nothing reaches `main` untested. | [Explanation 1](#explanation-1-why-domain-branches-stay-open-across-two-days) |
| 2026-09-25 / `3abfcc2` | Claude Code (Opus 5) | Asked which frontend approach to take given that section 1a permits only one dependency manifest at the repo root, and React requires `package.json` alongside `requirements.txt`. | **Rejected** | The recommendation was Jinja2 templates with vanilla JavaScript, to stay inside the one-manifest rule. I rejected it and secured written approval for React instead. The mitigation I required: `package.json` at the repo root rather than in a subfolder, and the compiled bundle committed to `static/dist`, so Node is build-time only and a clone plus `pip install` plus `python app.py` still serves the whole app. | [Explanation 2](#explanation-2-why-committing-the-built-bundle-is-what-makes-react-work-here) |
| 2026-09-25 / `3abfcc2` | Claude Code (Opus 5) | Asked for the project scaffold under the standing constraints in my brief: environment-driven configuration with no `.env` requirement, dependency injection at the composition root, and the domain packages laid out so neither imports the other. | Accepted | Produced `config.py`, `app.py`, `requirements.txt`, `pytest.ini`, `.coveragerc`, `.gitignore`, `README.md`. Verified before accepting: the server logs `Running on all addresses (0.0.0.0)`, honours `PORT` and `DATA_DIR`, and falls back to port 8000 on a malformed value rather than refusing to boot. | [Explanation 3](#explanation-3-how-the-configuration-layer-works) |
| 2026-09-25 / `3abfcc2` | Claude Code (Opus 5) | Asked for ADR-1 recording the backend framework choice, with the alternatives I had actually weighed. | Accepted | Drafted the Flask-over-Django/FastAPI entry. I accepted the reasoning as written and did not rewrite it. | [Explanation 4](#explanation-4-what-flask-gives-me-over-a-bare-wsgi-application) |
| 2026-09-29 / `feat/admin-auth` (step 0 of 3) | Claude Code (Opus 5.5) | "STEP 0: land the uncommitted admin-auth work first (branch: feat/admin-auth) … Check require_admin: it reads ADMIN_PASSWORD at request time (not import time), fails closed with 503 when unset, returns 401 on a wrong or missing password, compares with hmac.compare_digest (constant time, not ==), never logs or echoes the password, and has no default value anywhere." Full prompt: [the prompt for 2026-09-29](#prompt-for-2026-09-29-verbatim). | Accepted (merged as PR #4) | No code changed: `security.py`, the `Config.admin_password` field, the `/api/meta/schema` wiring and `tests/test_security.py` were reviewed against my checklist and passed it (8/8 tests). Split into three commits on `feat/admin-auth`: guard, wiring and tests, docs. | [Explanation 5](#explanation-5-the-shared-admin-password) |
| 2026-09-29 / `chore/stripe-scope` (step 1 of 3) | Claude Code (Opus 5.5) | "My professor has now asked me to integrate Stripe as well, so I can show more SOLID and design-pattern work. This reverses a decision in CLAUDE.md. Before editing, tell me every place this conflicts with CLAUDE.md or assignment_1.md. … Then edit CLAUDE.md only (no Stripe code today)." Full prompt: [the prompt for 2026-09-29](#prompt-for-2026-09-29-verbatim). | Modified | Found conflicts I had not listed: the public checkout endpoint is a second `@require_admin` exception, not just the webhook; a new `donations` column would not reach an existing database because `CREATE TABLE IF NOT EXISTS` never alters a table; and Stripe may not onboard businesses based in Jordan. I accepted per-staff accounts as ADR-5 and "refuse to charge" instead of "refuse to start" on an `sk_live_` key. I rejected the proposed AI_USAGE rule and set my own: one separate `AI_USAGE.md` commit at the end of each session, after I write my column. No code; CLAUDE.md only. | [Explanation 6](#explanation-6-bringing-stripe-into-scope) |
| 2026-09-29 / `feat/animal-intake-adoption` (step 2 of 3) | Claude Code (Opus 5.5) | "STEP 2: feat/animal-intake-adoption … Before coding, show me this proposed transition table and let me confirm it … parametrize over ALL 16 (from, to) pairs, so every allowed transition succeeds and every rejected one raises … ADR-2 in ADR.md: how the domains stay independently modularizable." Full prompt: [the prompt for 2026-09-29](#prompt-for-2026-09-29-verbatim). | Modified | I confirmed the transition table as proposed. I chose to add a `status_changes` table (history written in the same transaction as the race-safe UPDATE), public GETs showing vaccinations only, and placement requests deferred to the frontend days. I rejected two of its first drafts on review against my own rules: f-strings building SELECT column lists in `repository.py` (constants, but my rule is no f-strings in SQL at all), and an `import sqlite3` in the repository that broke `db/connection.py`'s claim to be the only importer. Result: 76 tests, 100% coverage on `domains/animals`; boundary test shown failing on a planted import. | [Explanation 7](#explanation-7-the-animal-intake-and-adoption-domain) |
| 2026-09-30 / `feat/donation-impact-ledger` | Claude Code (Opus 5.5) | "This is the second feature domain and the data behind the homepage counters (audit fix #1: numbers computed from real data at request time, never hardcoded). … BEFORE WRITING ANY CODE: confirm these decisions with me … Checking earmarked animals: donations declares a one-method AnimalDirectory Protocol (exists(animal_id) -> bool). create_app adapts AnimalService to it with a small adapter at the composition root, inside neither domain package." Full prompt: [the prompt for 2026-09-30](#prompt-for-2026-09-30-verbatim). | Modified | Before coding it found that my amount regex `^\d{1,5}(\.\d{1,3})?$` accepts Arabic-Indic digits (`٢٥` parses as 25) and a trailing newline; I accepted the fix (`[0-9]` with `fullmatch`) and it proved the test catches the `\d` version. It also found the schema already has `received_at` (no schema change needed) but no `note` column (dropped), and that `earmarked_animal_id` has no foreign key by design (ADR-3). I chose all its recommendations: append-only triggers in SQLite, `/api/animals/stats` today, and "today" meaning Amman (fixed UTC+3), now injected into both services. Result: 160 tests, 100% coverage on both domains, the boundary test green in both directions, ADR-4 written. | The donations domain declares a one-method Protocol, `AnimalDirectory.exists(animal_id) -> bool`, and depends only on that. In `create_app`, `AnimalDirectoryAdapter` wraps `AnimalService`: `exists` calls `AnimalService.get` and returns False when a "not found" error is raised. That is the Adapter pattern, and the only place that knows both domains; in tests a small fake with a fixed set of IDs replaces it. Money is stored as integer fils because floats can't represent most decimal amounts exactly (0.1 + 0.2 gives 0.30000000000000004) and the errors build up across the ledger's SUM. It arrives as the string `amount_jod` because a JSON number would already be a float before my code saw it; the text is checked against a strict pattern, converted with `Decimal` and multiplied by 1,000. Full explanation: [Explanation 8](#explanation-8-the-donation-and-impact-ledger). |
| 2026-10-01 / `feat/stripe-donations`, `feat/react-frontend` | Claude Code (Opus 5.5) | "SECRETS RULE, which overrides everything else today: never ask me to paste a key, never print, echo, log or write any value of STRIPE_SECRET_KEY or STRIPE_WEBHOOK_SECRET. … If JOD is NOT accepted, STOP. We decide together, because a second currency would break the fils-only SUM in the ledger. … PATTERN HONESTY TABLE … I must only claim what's really there." Full prompt: [the prompt for 2026-10-01](#prompt-for-2026-10-01-verbatim). | Modified | The JOD test failed: my Stripe test account cannot charge JOD at all, which overturned decisions 3 and 9 (JOD currency, 10-fils step). On its recommendation I chose to charge USD at the Central Bank of Jordan's fixed peg (709 fils per dollar), converted inside the Stripe adapter, with what Stripe actually charged kept in a new `stripe_payments` table as the audit trail; the ledger stays in fils. My own CLI test showed Stripe's real minimum is EUR 0.50 (the account settles in EUR), so `MIN_CHECKOUT_FILS` stays at 0.500 JOD as a margin. Gaps A and B as it recommended: a gift for a vanished animal is recorded as given with a warning; a charge that can't be expressed in fils is logged for staff and not recorded. It reordered my commits because the adapter imports the service's types (the consumer owns the interface), moved the fake gateway into the tests, also hid `admin_password` from `Config`'s repr, and switched off Stripe Adaptive Pricing after seeing it enabled in the live event. Live run: real test payment recorded once as 25.503 JOD for USD 35.97; a real resend of the same event answered 200 and added no row; forged signature 400; no keys and a dummy live key both 503 with no key material in the logs. 232 tests, 100% coverage. ADR-5 written; one sentence of ADR-4 corrected. Frontend (branch pushed, merges Oct 2): Vite + React at the repo root building into static/dist, Flask serving it with a fallback so React Router URLs reload while unknown /api paths stay JSON 404s. I rejected its first plain styling and asked for a warm, friendly design with animal photos; it built the restyle but flagged that no photos exist in the system, and I chose a staff photo-upload endpoint for Oct 2 (drawn species portraits until then) and a self-hosted Nunito font instead of Google Fonts (which would send visitors' IPs to Google). | `POST /api/donations/checkout` validates the request and asks `StripeGateway` for a payment page; nothing is written until Stripe sends a signed `checkout.session.completed` event to `/api/donations/stripe/webhook`. The signature is an HMAC-SHA256 of the timestamp and the exact body bytes under the shared `whsec_` secret, which is why the raw bytes are read before any JSON parsing. A replay can't count twice: `session_id` is UNIQUE, the payment insert uses `ON CONFLICT DO NOTHING`, and `_AlreadyRecorded` rolls back the donation row in the same transaction. The ledger records the verified `amount_total` because that is money that really moved; 25.500 JOD became $35.97 and came back as 25.503 JOD at the 709-fils peg. `StripeGateway` is the Adapter and the `PaymentGateway` Protocol lives in `service.py` (Dependency Inversion). Full explanation: [Explanation 9](#explanation-9-stripe-card-donations-and-the-start-of-the-react-frontend). |

---

## Explanation 1: why domain branches stay open across two days

If the feature and its tests went in as separate PRs, main would contain
untested business logic between the two merges. If work stopped at that point,
through illness or the October 4 deadline, the submitted codebase would include
code with no tests, and coverage is 15% of the grade. Keeping one branch open
across two days means main only ever receives a feature together with its tests.
Every merge leaves main in a state I would be happy to submit.

## Explanation 2: why committing the built bundle is what makes React work here

The Assignment 2 deployment script runs only git clone, pip install -r
requirements.txt and python app.py. It never runs npm install or npm run build,
and the target machine may not have Node installed at all. Without a committed
static/dist, the clone would contain no HTML, CSS or JavaScript, so Flask would
start but serve nothing. Committing the compiled bundle means the frontend
arrives with the clone. Node is needed only on my machine, and only when I
change the frontend. The running application never needs it: I commit the
photograph, not the camera.

## Explanation 3: how the configuration layer works

load_config() reads os.environ once at startup. It returns a single Config
object holding host, port, data_dir and debug, with each value converted from a
string to its real type: port to an int, data_dir to a Path and debug to a bool.
The dataclass is frozen=True, so assigning to a field after construction (for
example config.port = 9999) raises an error. That matters because everything
downstream assumes the config never changes. The Database is built from
config.database_path, so if later code could reassign data_dir, the database
would still point at the old file while the rest of the app believed it had
moved. Freezing makes that bug impossible rather than just unlikely.
database_path is a @property computed as data_dir / "alrahmeh.db", so only one
line in the project knows the filename, and it can never drift out of sync with
data_dir.

create_app() accepts an optional Config (config = config or load_config()) for
testing. A test can pass Config(host="0.0.0.0", port=8000, data_dir=tmp_path,
debug=False) and get a database in a temporary folder. It never has to set
os.environ["DATA_DIR"], which would change global state for the whole test
process and could leak into later tests. This is dependency injection, and
create_app() is the composition root: the one place where concrete objects are
built and wired together.

_read_port() returns 8000 in three cases: when PORT is unset, when it is not a
number and when it is outside 1–65535. The deployment script starts the process
with nobody watching, so raising an error would turn a typo like PORT=80OO into
a dead site. Falling back keeps the app running and logs a warning with the
reason. The trade-off is that silently ignoring configuration can hide a
mistake, and if the host requires a specific port, starting on the wrong one
fails quietly instead of loudly. I chose availability because an unattended
deployment has nobody there to read a crash.

## Explanation 4: what Flask gives me over a bare WSGI application

A bare WSGI app would make me hand-write URL parsing, method dispatch, JSON
serialisation, error-to-status mapping and a test harness. Flask gives me
routing decorators, jsonify(), Blueprints (the boundary that lets each domain
own its routes without importing the other) and app.test_client(), which
exercises every endpoint without starting a server or binding a port.

## Explanation 5: the shared admin password

This stage of the project has three parts, each on its own feature branch and
merged into main through a pull request. First, I brought in shared-password
authentication for staff actions. Second, I updated the project scope to include
Stripe payments, which my professor asked for so the project can show more
SOLID principles and design patterns. Third, I built the first of the two
feature domains: animal intake and adoption. This domain gives the rescue real
animal records with a guarded placement lifecycle. Replacing the Google Forms
"Adopt Now" and "Foster Now" links with a request workflow built on these
records (`placement_requests`) is deliberately deferred to the frontend stage.

The organisation has a small team, so I chose one shared staff password over
individual user accounts. The password is read once at startup from the
`ADMIN_PASSWORD` environment variable into the application's `Config` object. A
decorator in `security.py`, `require_admin`, checks each staff request against
that stored value. Because the value is read once, changing the password means
restarting the application. Every endpoint that creates or changes data carries
this decorator.

The design fails closed. If no password is configured, staff endpoints answer
with HTTP 503 and do not allow access. There is no default password anywhere in
the code. A missing or wrong password in the request gets HTTP 401. The
comparison uses `hmac.compare_digest`, which takes the same time whether a guess
is nearly right or completely wrong. This stops an attacker from working out the
password by timing responses. `tests/test_security.py` checks all three cases:
not configured, wrong password and correct password.

**Q: Why 503 and not 401 when no password is set?** A 401 means "your
credentials are wrong, try again." When no password is configured, no
credential could ever succeed. The problem is on the server, not with the person
making the request. A 503 ("service unavailable") says exactly that: this
feature is switched off until whoever runs the server fixes the configuration.
It also makes the two failures easy to tell apart in logs. A wave of 401s
suggests someone is guessing passwords. A 503 means a setting is missing.

## Explanation 6: bringing Stripe into scope

My original plan named Stripe as the feature I deliberately chose not to build
(ADR-5). After my professor asked me to integrate it, I updated the project
brief (`CLAUDE.md`) to show the new scope and replaced ADR-5's subject with
another feature left out on purpose. This part changes documentation and
planning only. The payment code will be written on its own branch,
`feat/stripe-donations`, after the donation ledger exists.

The updated brief sets the rules the payment integration must follow:

- **Adapter pattern and Dependency Inversion.** The donation service depends on
  a `PaymentGateway` interface, not on Stripe directly. A Stripe adapter
  implements the interface in production, and a fake adapter implements it in
  tests. Which one is used is decided in one place, `create_app`.
- **Trustworthy ledger.** A donation is recorded only after Stripe itself
  confirms it through a signed webhook (a message Stripe sends to our server).
  The browser redirect and any amount the donor's browser sends are never
  trusted. Each Stripe Checkout session ID is stored as unique, so a repeated
  confirmation for the same payment cannot count the donation twice.
- **Safe configuration.** Stripe keys come only from environment variables, are
  never committed or logged, and only test-mode keys are accepted.
- **Two documented exceptions to `@require_admin`.** Both payment write
  endpoints are open by necessity:
  - The checkout endpoint, which starts a payment. Donors are members of the
    public, so they can't be asked for the staff password.
  - The webhook endpoint, which Stripe calls to confirm a payment. Stripe can't
    provide the staff password either, so this endpoint is authenticated by
    checking Stripe's cryptographic signature instead.

**Q: Why does a live key block payments but not startup?** If
`STRIPE_SECRET_KEY` holds a live key (`sk_live_...`), the application still
starts, and only the payment endpoints refuse to work: they return 503 and log a
warning. The alternative, refusing to start at all, would let one payment
misconfiguration take down the whole site, including animal profiles and the
impact counters that have nothing to do with payments. It would also break the
requirement that the app starts without anyone needing to step in. Disabling
only the affected feature follows the same fail-closed approach as
`ADMIN_PASSWORD`: real charges are still impossible, and everything else keeps
running.

## Explanation 7: the animal intake and adoption domain

The domain is in `domains/animals/`. It follows a layered structure where each
file has one job.

**Models (`models.py`).** This file defines what the domain works with and
checks incoming data. `Animal` holds an animal's name, species, breed, intake
date and current placement status. Medical and vaccination history are held as
separate records linked to the animal. Placement status is an enumeration,
`PlacementStatus`, with four values: AVAILABLE, FOSTERING, PENDING and ADOPTED.
Using an enumeration instead of plain text strings means a misspelt status is
caught immediately instead of being saved silently.

Input validation lives here too, in `NewAnimal.from_payload`. It takes the raw
data from a request, checks it (required fields present, dates valid) and
either returns a clean `NewAnimal` object or rejects the input. Because
validation happens when the object is built, the rest of the domain never
receives an invalid animal and doesn't need to check again.

**Repository (`repository.py`).** The repository is the only part of the domain
that contains SQL. `SqliteAnimalRepository` stores and retrieves animals, status
history and medical records using Python's built-in `sqlite3` module. All
queries are parameterised, which prevents SQL injection.

The status update is written to be safe when two people act at once. It changes
the row only if the animal is still in the expected status. So if two staff
members act on the same animal at the same moment, only one change succeeds and
the other is rejected rather than silently overwriting it.

**Service (`service.py`).** `AnimalService` holds the business rules. Two
important definitions live in this file.

The repository contract. `AnimalRepository` is a Protocol: a description of the
operations the service needs, with no database code. Defining it in the service
file rather than the repository file is deliberate. The high-level business
logic states what it needs, and the low-level SQLite code must conform to it.
The service never imports SQLite, and the repository is handed to it when it is
created.

The transition table. Allowed movements between statuses are written as a
lookup table, `ALLOWED_TRANSITIONS`:

| From | May move to | Real-world meaning |
|---|---|---|
| Available | Fostering, Pending | Placed with a foster, or an adoption application received |
| Fostering | Available, Pending | Foster returned the animal, or an application received |
| Pending | Available, Adopted | Application withdrawn, or adoption finalised |
| Adopted | (none) | Adoption is final |

Fostering is a full state rather than an afterthought, because fostering is
central to how Al-Rahmeh actually works. Any move outside this table is rejected
with a domain error naming both statuses, such as "cannot move from adopted to
available."

The service's main operations are:

- `admit`:  takes the raw request payload. It calls
  `NewAnimal.from_payload` itself, then `repository.add`. That is why the
  routes never validate anything.
- `get` and `list_animals`: fetch one animal or a list of them.
- `transition`: checks the requested move against `ALLOWED_TRANSITIONS`, then
  either saves it or rejects it.
- `status_history`: returns the record of every status change for an animal.
- `record_medical`: adds a medical or vaccination entry.
- `medical_history` and `vaccinations`: return an animal's full medical record,
  or its vaccinations only.

**Routes (`routes.py`).** The routes form a Flask blueprint that exposes the
service as a JSON API:

| Endpoint | Access | Purpose |
|---|---|---|
| `GET /api/animals` | Public | List animals |
| `GET /api/animals/<id>` | Public | View one animal, with vaccinations only |
| `GET /api/animals/<id>/staff` | Staff | Full record, including medical history |
| `POST /api/animals` | Staff | Admit a new animal |
| `POST /api/animals/<id>/transitions` | Staff | Change placement status |
| `POST /api/animals/<id>/medical-records` | Staff | Add a medical record |

The split between public and staff views is deliberate. Vaccinations are useful
to a potential adopter, while detailed medical notes are internal to the
organisation.

Route handlers contain no business logic. They read the request, call the
service and turn the result into JSON. Errors map to the right HTTP codes: 400
for invalid input, 404 for a missing animal, 409 for an illegal transition, and
401 or 503 for authentication problems. Error responses never include stack
traces or database details.

**Wiring (`app.py`).** All the parts are connected in one place, `create_app`.
It builds the SQLite repository, passes it into `AnimalService`, and registers
the blueprint with that service. This is the composition root: the only place
where concrete classes are chosen.

**Applying SOLID and design patterns.**

- **Single Responsibility:** models describe and validate data, the repository
  stores it, the service enforces rules, and routes handle HTTP. Each layer has
  one reason to change.
- **Open/Closed:** allowed transitions are data in a table, not a chain of if
  statements. Changing the rules means editing one table, not rewriting logic.
- **Liskov Substitution:** the service works with anything that satisfies the
  `AnimalRepository` contract. The tests show this with a `StaleRead` wrapper
  around the real repository. It reports an out-of-date status, simulating a
  second staff member who changed the animal a moment earlier. The service runs
  against this substitute unchanged and correctly rejects the late change as a
  lost race.
- **Interface Segregation:** the `AnimalRepository` protocol lists only the
  operations the service actually uses, not everything the SQLite class could
  do.
- **Dependency Inversion:** the protocol is defined by the service that needs
  it, in `service.py`, and the SQLite repository conforms to it. The high-level
  rules don't depend on the database. The database code depends on the rules'
  contract. The concrete class is injected at the composition root.
- **Patterns used:** Repository (hiding the database behind an interface) and
  Dependency Injection. I deliberately did not use the State or Strategy pattern
  for transitions. A simple lookup table is clearer, and forcing a pattern where
  it doesn't fit would make the code worse.

**Q: What would adding a `medical_hold` status take?** For example, an animal
that is unwell and temporarily can't be placed. Three places would change:

- **The enum:** add `MEDICAL_HOLD` to `PlacementStatus` in `models.py`.
- **The transition table:** add rows to `ALLOWED_TRANSITIONS` in `service.py`,
  such as available → medical_hold, fostering → medical_hold, and
  medical_hold → available. No other service code changes, which is the
  Open/Closed design paying off.
- **The schema:** the database's CHECK constraints only accept the four current
  statuses, so they must include the new value. Here I hit a real limitation.
  SQLite can't modify a CHECK constraint on an existing table, and
  `CREATE TABLE IF NOT EXISTS` never touches a table that already exists. New
  installations would pick up the change, but an existing database would need a
  migration that rebuilds "animals". `status_changes` also has CHECK constraints on `from_status` and
  `to_status`, so the migration rebuilds two tables, not one.

The parameterised transition test would also grow from 16 combinations to 25.

**Keeping the domains independent (ADR-2).** The animals package never imports
the donations package, and the reverse is also true. The two refer to each other
only by ID values. This boundary means either domain could later be split into
its own service without rewriting the other. It is enforced by an automated
test that fails if such an import ever appears. The decision is recorded in
ADR-2 using the required Context / Decision / Alternatives considered /
Consequences format.

**Testing and verification.** `tests/test_animals_service.py` tests the service
and models against a real SQLite database rather than a simulated one, so the
SQL is exercised as well. One parameterised test runs through all 16 possible
status combinations (four statuses moving to four statuses). It confirms that
the 6 allowed moves succeed and the other 10 are rejected. Further tests cover
invalid input, missing animals, and the lost-race case using the `StaleRead`
wrapper. Test coverage is measured with pytest-cov, focused on business logic
rather than routing code.

I also started the application and exercised it with sample requests. These
confirmed that an unauthenticated write is refused (401), an authenticated one
succeeds (201), a legal transition is accepted (200) and an illegal one is
rejected (409). The work was committed in logical steps (models, repository,
service and tests, routes and wiring, then ADR-2), so the history shows how the
feature was built.

## Explanation 8: the donation and impact ledger

This stage builds the second feature domain, the donation and impact ledger, on
the branch `feat/donation-impact-ledger`. It records every donation the rescue
receives and computes the impact statistics shown on the homepage. This directly
fixes the first problem from my audit: the live site's counters ("More than 300
pets found homes...") were typed into the HTML by hand. In the rebuild, every
figure is calculated from real records at the moment the page asks for it.

The domain is in `domains/donations/` and follows the same four-layer structure
as the animals domain: models, repository, service and routes.

**Models (`models.py`).** This file defines the donation data and checks
incoming requests.

- `DonationPurpose` is an enumeration with three values: MEDICAL_FUND, FOOD_FUND
  and GENERAL. Its values match the database's CHECK constraint exactly, and a
  test fails if the two ever drift apart.
- `Donation` is a stored ledger record: amount, purpose, the date it was
  received, an optional donor name, and an optional earmarked animal.
- `NewDonation.from_payload` takes the raw data from a request, validates it and
  returns a clean `NewDonation` object, or rejects the request. It uses the same
  validation style as the animals domain: unknown fields are rejected, required
  fields must be present, text fields have length limits and dates must be
  valid.
- `ImpactSummary` holds the calculated statistics returned to the homepage.

Three rules apply to every donation:

- **Amount limit.** The amount must be above zero and at most 10,000 JOD, stored
  as the named constant `MAX_DONATION_FILS`. This catches typing mistakes such
  as an extra zero.
- **Received date.** Cash is often recorded days after it arrives, so staff can
  enter an optional `received_on` date. It can't be in the future and defaults
  to today.
- **Deliberate duplication.** Some validation helpers repeat logic from the
  animals domain. I accepted that small duplication on purpose: sharing the code
  would force one domain to import the other, which the independence rule
  (ADR-2) forbids.

**Repository (`repository.py`).** The repository is the only donations code that
runs SQL. It has four operations: adding a donation, fetching one, listing
donations, and the aggregate queries behind the statistics.

The ledger is append-only, and that is enforced by the code's shape. The
repository has no update or delete methods at all, so no part of the application
can change or remove a recorded donation. A test confirms these methods don't
exist. The HTTP API matches: PUT and DELETE requests on a donation return 405
("method not allowed"). Beneath that, two SQLite triggers make the database
itself refuse any UPDATE or DELETE on the donations table, so even code that
bypasses the repository cannot change the ledger, and a test proves it.

A consequence is that mistakes can't be corrected yet. The schema comment
originally said "a correction is a new compensating row." That was impossible,
because the database requires every amount to be greater than zero, so a
negative correction row can never be stored. I rewrote the comment to state
honestly that corrections aren't supported yet, and recorded this as a known gap
in ADR-4.

The statistics use SQL SUM, COUNT and GROUP BY, so the database does the
arithmetic. COALESCE makes an empty ledger return 0 rather than nothing. All
three purposes appear in the per-purpose totals even when one of them has
received nothing yet. All queries are parameterised, and database rows are
converted to dataclasses before they leave this file.

**Service (`service.py`).** `DonationService` holds the business rules. As in
the animals domain, the service defines the contract it needs, the
`DonationRepository` Protocol, and the SQLite repository is handed to it when it
is created.

The service provides:

- Recording a donation. It checks that any earmarked animal really exists, then
  saves the donation.
- Listing donations, with a limit and offset so the list can never be returned
  unbounded.
- Calculating impact statistics from the ledger each time they are requested.
  Nothing is cached, hardcoded or kept as a running total, so the homepage
  figures can never fall out of date.

"Today" is passed into the service as a small clock function instead of the
service calling `date.today()` itself. This lets the tests fix the date and
check the "no future dates" rule reliably. The clock uses Asia/Amman time (a
fixed UTC+3 offset, since Jordan has no daylight saving), so the date matches
the rescue's local day even on a server that runs in UTC.

**Routes (`routes.py`) and wiring.**

| Endpoint | Access | Purpose |
|---|---|---|
| `POST /api/donations` | Staff | Record a cash or bank-transfer donation |
| `GET /api/donations` | Staff | List donations, paginated |
| `GET /api/donations/<id>` | Staff | View one donation |
| `GET /api/donations/impact` | Public | Impact statistics for the homepage |

Listing donations is staff-only because donor names are private. The public
impact endpoint returns totals only and never exposes an individual donation or
donor. Route handlers contain no business logic. Errors map to 400 for invalid
input or a missing earmarked animal, 401 or 503 for authentication problems, and
405 for update or delete attempts.

**The homepage statistics.** The public impact endpoint returns four figures:

- the total raised, all time;
- the total for each purpose (medical, food and general);
- the number of donations;
- the number of distinct animals helped through earmarked gifts. Two gifts to
  the same animal count as one.

I deliberately did not include a "number of donors." Donor names are optional,
so anonymous gifts would make any donor count inaccurate, and I didn't want the
homepage to show a number I couldn't back up.

The original site's "pets found homes" figure is an adoption count, which
belongs to the animals domain, not the donation ledger. I added a small public
endpoint, `GET /api/animals/stats`, that returns the number of animals in each
placement status. The homepage will call both endpoints separately. Combining
them into one backend endpoint would have tied the two domains together.

**How the donations domain checks that an animal exists.** A donor can earmark a
gift for a specific animal, for example to pay for one dog's surgery. The
donations service must refuse an earmark to an animal that doesn't exist.
However, the donations package is not allowed to import the animals package
(ADR-2). The two domains may only refer to each other by ID number.

I solved this in three pieces.

1. **The donations domain states what it needs.** Inside `domains/donations/`, I
   defined a Protocol called `AnimalDirectory` with exactly one method:
   `exists(animal_id) -> bool`. The donations service depends only on this small
   contract. It has no idea animals are stored in a database or managed by
   `AnimalService`.
2. **An adapter connects the two, outside both domains.** In `create_app`, the
   composition root, a small class called `AnimalDirectoryAdapter` wraps the
   existing `AnimalService`. Its `exists` method calls
   `AnimalService.get(animal_id)` and returns True if the animal is found, or
   False if a "not found" error is raised. This is the only place in the
   codebase that knows about both domains.
3. **`create_app` passes the adapter in.** When the application starts, it
   builds the `AnimalService`, wraps it in the adapter, and hands the adapter to
   `DonationService` as its `AnimalDirectory`.

This is the Adapter pattern: `AnimalService` has an interface of its own that
doesn't match what donations expects, and the adapter converts one into the
other without either side changing. It also shows:

- **Dependency Inversion:** the donations service depends on a contract it owns,
  not on the animals code.
- **Interface Segregation:** donations sees one method, not the whole of
  `AnimalService`.
- **Liskov Substitution:** in tests, a small fake directory with a fixed set of
  IDs replaces the adapter. The service can't tell the difference.

The automated boundary test checks both directions (animals never imports
donations, and donations never imports animals) and still passes. If the domains
were later split into separate services, only the adapter would change: instead
of calling `AnimalService` directly, it would make an HTTP request to the
animals service. The donations code itself would stay the same.

**Why money is stored as integer fils and received as a string.** The Jordanian
dinar divides into 1,000 fils, so 25.500 JOD is 25,500 fils. The ledger stores
every amount as a whole number of fils (`amount_fils`), and the API receives
amounts as text (`"amount_jod": "25.500"`). There are two reasons.

1. **Decimal numbers in computers are inexact.** Most programming languages,
   including Python, store decimal numbers as binary floating-point values
   ("floats"). Many everyday amounts, such as 0.1, can't be represented exactly
   in binary, only very close approximations. In Python, `0.1 + 0.2` gives
   `0.30000000000000004`. For one donation the error is tiny. But the ledger
   adds up every donation ever recorded, and those small errors build up, so a
   total can end up a fraction of a fils off. For financial records that is
   unacceptable. Whole numbers don't have this problem: 25,500 + 100 is always
   exactly 25,600, and SQLite stores and sums integers exactly. Storing fils as
   integers is the ADR-3 schema decision.
2. **A JSON number would already be a float before my code saw it.** If the API
   accepted `"amount_jod": 25.5` as a JSON number, Python's JSON parser would
   turn it into a float immediately, and the precision problem would start
   before any validation could run. Sending the amount as text means it reaches
   my code exactly as the staff member typed it. The model then:
   - checks the text against a strict pattern: digits, optionally a decimal
     point, and at most three decimal places. This rejects values such as
     "1e3", "NaN", "Infinity", "-5" and "25.5555" before they are converted;
   - converts the text with Python's `Decimal` type, which works in exact
     decimal arithmetic;
   - multiplies by 1,000 to get a whole number of fils.

A request that sends the amount as a JSON number is rejected with a message
asking for a string.

The alternative I considered was accepting whole fils directly
(`"amount_fils": 25500`). It would be simpler to code, but staff would have to
type 25500 to record 25.5 dinars, which invites exactly the extra-zero mistakes
the upper limit is there to catch.

For output, responses include both `amount_fils` (the exact integer) and
`amount_jod` (a ready-formatted string such as "25.500"). The string is built
with whole-number division and remainder on the fils value, never floats. So the
frontend displays money without doing any currency arithmetic itself.

**Applying SOLID and design patterns.**

- **Single Responsibility:** models validate, the repository stores and
  aggregates, the service applies rules, routes handle HTTP, and money
  formatting is one small function.
- **Open/Closed:** per-purpose totals loop over the `DonationPurpose`
  enumeration, so a new fund needs only a new enum value and a database
  constraint update, not new code paths.
- **Liskov Substitution:** the fake animal directory and the real adapter behave
  identically: they take an ID and return true or false, never raising for "not
  found."
- **Interface Segregation:** `AnimalDirectory` has one method, and
  `DonationRepository` lists only what the service uses.
- **Dependency Inversion:** the service depends on Protocols it owns, and
  concrete classes are chosen only in `create_app`.
- **Patterns used:** Repository, Dependency Injection, and Adapter. Adapter is
  used because it genuinely solves the cross-domain problem, not to add a
  pattern for its own sake.

**Security and privacy.**

- All SQL uses parameterised queries.
- Recording and listing donations require the staff password.
- Donor names appear only in the staff list, never in the public statistics,
  logs or error messages.
- Text fields are length-limited and stored as plain text. The frontend must
  never render them as raw HTML.
- Every typed field rejects values of the wrong type, including booleans, which
  Python otherwise treats as numbers.

**Testing approach (ADR-4).** `tests/test_donations_service.py` covers:

- every validation rule, including malformed amount strings;
- the 10,000 JOD limit, both exactly at it and one fil over;
- an earmark to a missing animal, using the fake directory;
- the ledger's append-only shape;
- the statistics on an empty ledger and on a mixed one, including per-purpose
  totals and distinct animals.

ADR-4 records my testing approach. I prioritised the parts where a bug would do
real damage: all 16 placement transitions, input validation, the lost-race
case, append-only storage and the money aggregates. I left some areas thin, and
said why:

- Route files are excluded from coverage because they contain no business
  logic.
- There are no true multi-threaded race tests.
- There are no frontend tests yet.
- Stripe will only ever be tested through a fake adapter, never against the real
  service.
- Donation corrections aren't supported yet.

With this entry, the ADRs land on three different commit dates (28, 29 and 30
September), which meets the assignment requirement.

**Verification.** I ran the full test suite with coverage across both domains
and recorded the real figure in the README, marked provisional until the final
run on 4 October. I then started the application and checked it with sample
requests:

- an empty ledger returned zero totals for all three purposes;
- a donation without the password was refused (401) and with it was accepted
  (201);
- invalid amounts were rejected (400);
- an earmark to a missing animal was rejected (400);
- the totals updated immediately after new donations;
- update and delete attempts were refused (405).

The boundary test still passed in both directions, and the work was committed in
separate logical steps: models, repository, service and tests, routes and
wiring, the animal statistics endpoint, README coverage, then ADR-4.

## Explanation 9: Stripe card donations and the start of the React frontend

On 1 October I added online card donations to the donation domain and started
the React frontend. The card work was built on `feat/stripe-donations` (7
commits, merged through a pull request). The frontend was started on
`feat/react-frontend` (4 commits, pushed, merging on 2 October).

Before writing any payment code, I tested what my Stripe account could actually
do. That test changed the design: Stripe could not charge in Jordanian dinars at
all. The rest of this section explains how I handled that without breaking the
ledger's rule that every amount is stored in fils.

### Preparation and the currency problem

I created a Stripe account in test mode, where no real money moves. I installed
the Stripe command-line tool after checking its SHA-256 checksum (a fingerprint
of the file) against the one Stripe publishes, which confirmed the download
hadn't been tampered with. I entered my secret keys through a `Read-Host`
prompt, so they never reached PowerShell's history file. I only ever checked
them by their prefix (`sk_test_`), and the AI assistant never saw them.

The currency test failed. My account, registered in Spain, could not charge in
JOD or in any other currency with three decimal places. A second test showed
the real minimum charge is €0.50, because a Spanish account settles in euros.

I considered three options:

| Option | Outcome |
|---|---|
| Charge in US dollars and convert at the Central Bank of Jordan's fixed rate (1 USD = 709 fils, unchanged since 1995) | **Chosen** |
| Store several currencies in the ledger | Rejected: a large redesign, and the totals would no longer be a simple sum |
| Charge in euros | Rejected: the euro's rate against the dinar changes daily, so any fixed rate would be made up |

The conversion happens only inside the Stripe adapter, so the ledger still
stores whole fils, as ADR-3 requires. For a full audit trail, the exact amount
and currency Stripe charged are saved next to each card donation.

### What was built: Stripe donations

**Configuration (`config.py`).** Three new settings are read from the
environment:

- `stripe_secret_key` and `stripe_webhook_secret`, which have no default values;
- `public_base_url`, which must be a bare address such as
  `https://example.org`. An invalid value switches payments off instead of
  guessing.

Secret fields are hidden from the configuration's printed form. While adding
this, I found and fixed an existing leak: the admin password used to appear
whenever the configuration object was printed.

**Dependency.** `stripe==15.6.1` was added to `requirements.txt`, pinned to the
exact version installed.

**Database (`schema.sql`).** A new table, `stripe_payments`, links each card
payment to its ledger row. It stores the Stripe session ID (unique), the
donation ID (also unique), and the amount and currency actually charged. I
added a new table instead of new columns because `CREATE TABLE IF NOT EXISTS`
never modifies a table that already exists, so new columns would never reach
existing databases.

**Models (`models.py`).**

- `CheckoutRequest.from_payload` validates a donor's request by reusing the
  existing amount, purpose and earmark checks. It adds a minimum of 500 fils
  (`MIN_CHECKOUT_FILS`), which keeps every charge above Stripe's €0.50 minimum.
- Three new types describe payments without mentioning Stripe:
  `CheckoutSession`, `ProviderCharge` and `PaymentConfirmed`. If a charge can't
  be converted to fils, `PaymentConfirmed.amount_fils` is empty (`None`).

**Repository (`repository.py`).** `add_paid` saves a card donation in one
transaction:

1. it inserts the donation row;
2. it inserts the payment row with `ON CONFLICT (session_id) DO NOTHING`;
3. if the payment row wasn't inserted, it raises a private `_AlreadyRecorded`
   error, which cancels the whole transaction, donation row included.

Staff-recorded and card donations share a single insert function,
`_insert_donation`, so there is one way to add a row to the ledger.

**Service (`service.py`).**

- The `PaymentGateway` Protocol is defined here, owned by the service. It has
  two methods: `create_checkout` and `verify_event`.
- New errors and outcomes: `PaymentsUnavailable`, `InvalidWebhookSignature`,
  `PaymentProviderError` and the `WebhookOutcome` enumeration.
- `start_checkout` validates the request, checks the earmarked animal, asks the
  gateway for a payment page and writes nothing to the ledger.
- `handle_webhook` has the gateway verify the incoming message, then records the
  payment.
- Two edge cases are handled deliberately:
  - **Gap A:** a donation earmarked for an animal that no longer exists is still
    recorded, and a warning is logged.
  - **Gap B:** a payment that can't be expressed in fils, is outside the allowed
    range, or has an unknown purpose is marked `NEEDS_RECONCILIATION`. Nothing
    is recorded, and only the session ID is logged.

**Stripe adapter (`payments.py`).** This is the only file that imports the
Stripe library, and a test enforces that.

- `StripeGateway.create_checkout` asks Stripe for a card-only, one-off payment
  in US dollars. It converts the fils amount to cents, attaches the purpose,
  earmark and donor name as metadata, and builds the return addresses from
  `PUBLIC_BASE_URL`.
- It switches off Stripe's Adaptive Pricing, which could otherwise show the
  donor a different currency.
- It sends the secret key with each request rather than setting it globally.
- `verify_event` checks the webhook signature with a 300-second time window and
  ignores everything except a completed, paid checkout. It converts cents back
  into fils using whole-number rounding.

**Routes (`routes.py`).** There are two public endpoints, each commented as one
of the only two exceptions to `@require_admin`:

- `POST /api/donations/checkout` accepts JSON only;
- `POST /api/donations/stripe/webhook` reads the raw request bytes before
  anything parses them.

Errors map to 400 (bad input or bad signature), 503 (payments unavailable) and
502 (Stripe unreachable).

**Wiring (`app.py`).** `_payment_gateway(config)` decides whether payments are
enabled. It refuses live keys and missing keys, logs the reason without ever
logging a key, and returns `None` in those cases. Request bodies are limited to
64 KiB.

**ADRs.** ADR-5 now records the regional-gateway decision. One sentence in
ADR-4 was corrected, because the real Stripe adapter is now tested directly, not
only through a fake.

### Testing and verification

The test suite has 232 tests with 100% coverage of the measured code. Webhook
messages are signed locally with a dummy secret, so no network is needed.
Stripe's session creation is replaced with a stand-in during tests, and a test
checks that only `payments.py` imports the Stripe library.

The live run confirmed the whole flow:

- A test payment with card 4242 4242 4242 4242 charged $35.97, which was
  recorded once as 25.503 JOD.
- Resending the same Stripe event returned 200 and added no second row.
- A forged signature was rejected with 400.
- With no keys, and with a dummy live key, the payment endpoints returned 503,
  and no key appeared in the logs.
- The live event showed Adaptive Pricing was still on, so I switched it off.

### Frontend: the first four commits

- **Build setup.** `package.json` and its lockfile sit at the repository root,
  and `vite.config.js` builds `frontend/` into `static/dist`. During
  development, `/api` requests are forwarded to Flask. There are now 10 declared
  dependencies, under the limit of 12.
- **Serving.** `_register_frontend_routes` in `app.py` does three things:
  - serves real build files;
  - returns `index.html` for any other address not starting with `/api`;
  - returns a JSON 404 for unknown `/api` addresses.

  Files are served with `send_from_directory`, so nothing outside the build
  folder can be read. The `.woff2` font type is registered so browsers accept
  the font files.
- **API client.** `api.js` is the only code that calls `fetch`. It turns every
  failure into one `ApiError` type and provides a `useApi` hook for the pages.
- **Visual design.**
  - `art.jsx` holds line icons and drawn species portraits.
  - `animals.jsx` holds the list, filter chips, cards, profile page and friendly
    status sentences.
  - `styles.css` holds a warm palette, soft shapes, hover effects and a
    reduced-motion setting.
  - The Nunito font is bundled as two `.woff2` files.
- **Photos.** A staff photo-upload endpoint is planned for 2 October. Until
  then, each card shows a drawing of the animal's species.

### Answers to the review questions

#### Card donations

**1. Walk one card donation from the button to the ledger row.**

1. The donor fills in the donate form and presses the button. The browser sends
   `POST /api/donations/checkout` with the amount, purpose, any earmarked animal
   and an optional name. (The donate form itself arrives on 2 October; in
   today's live run the same request was sent directly.)
2. The server validates the request (`CheckoutRequest.from_payload`), checks the
   earmark, and asks `StripeGateway` to create a Checkout session. Stripe
   returns a session ID and a payment-page address. Nothing is written to the
   ledger yet.
3. The browser receives that address as JSON and redirects the donor to
   Stripe's hosted payment page.
4. The donor enters their card details on Stripe's page, not ours. Card numbers
   never reach our server, which keeps us out of most card-security
   obligations.
5. After payment, Stripe does two separate things:
   - it sends the donor's browser to `/donate/thanks`, which only ever says
     thank you and writes nothing;
   - it sends a `checkout.session.completed` event to
     `POST /api/donations/stripe/webhook`. During development, `stripe listen`
     forwarded this event to my local server.
6. The webhook route passes the raw message to the service. The gateway
   verifies the signature and converts the event into a `PaymentConfirmed`.
   `confirm_payment` then calls `add_paid`, which writes the ledger row and the
   `stripe_payments` row together, and the server answers 200.

**2. How does the webhook prove a message really came from Stripe?**
Stripe and my server share a secret, the `whsec_...` webhook secret, which
nobody else knows. For each message, Stripe takes the send time and the exact
bytes of the body, and computes an HMAC-SHA256 code from them using that secret.
It sends the time and the code in the `Stripe-Signature` header. My server,
through `stripe.Webhook.construct_event`, recomputes the code from the bytes it
received and compares the two. Anyone without the secret can't produce a
matching code, so a forged message fails. The time is also checked: a message
more than 300 seconds old is rejected, so a captured message can't be replayed
much later.

`request.get_data()` must run first because the code covers the exact bytes. If
the body were parsed as JSON and turned back into text, details such as
spacing, key order or how special characters are written could change. The
code would then no longer match, even for a genuine message.

**3. What stops a replayed webhook from counting twice?**
The `session_id` column in `stripe_payments` is UNIQUE, so the database itself
won't store the same session twice. `add_paid` inserts the donation first,
because the payment row needs its ID, and then inserts the payment row with
`ON CONFLICT (session_id) DO NOTHING`. On a replay, that second insert does
nothing. The code notices no row was added and raises `_AlreadyRecorded` while
the transaction is still open. That cancels the whole transaction, so the
donation row inserted a moment earlier is removed too. The service reports
"already recorded" and the route answers 200.

Checking first with a SELECT and then inserting would be unsafe because of
timing. Stripe can deliver the same event twice almost at once. Both requests
could run the check, both find nothing, and both insert, counting the donation
twice. Letting the database enforce uniqueness in a single step closes that
gap.

**4. Why trust `amount_total` from the verified event but never the amount the
browser asked for?**
Anything coming from the browser can be changed by whoever controls it, and a
requested amount is only a request. The donor might never complete the
payment, or someone could tamper with the request. `amount_total` comes inside
a message signed by Stripe and states what was actually charged. The ledger is
a financial record, so it records money that really moved.

**5. You asked to give 25.500 JOD. Why did the ledger record 25.503?**
The peg is 1 USD = 709 fils, so 1 cent = 7.09 fils.

- Fils to cents (`fils_to_cents`): 25,500 fils × 100 ÷ 709 = 3,596.61 cents,
  rounded to 3,597 cents = $35.97. Stripe charged this.
- Cents back to fils (`cents_to_fils`): 3,597 cents × 709 ÷ 100 = 25,502.73
  fils, rounded to 25,503 fils = 25.503 JOD. The ledger recorded this.

A cent is about seven times coarser than a fil, so converting to cents means
rounding, and the donor can only be charged a whole number of cents. The ledger
records what $35.97 is actually worth in fils, not what was asked for. That is
the honest figure, and the gap is never more than about 3.5 fils.

**6. Why charge in USD, and why is the peg defensible when EUR wouldn't be?**
I charge in USD because my Stripe account can't charge in JOD or any other
three-decimal currency. The peg is defensible because the Central Bank of
Jordan has held the dinar at 0.709 per US dollar since 1995. The rate is
official, public and unchanged, so the conversion gives the same answer every
time and an accountant can check it. The euro's rate against the dinar changes
every day. A fixed euro rate would be one I made up, and a live rate would need
an outside data service the project doesn't have. For a full audit trail, the
actual amount and currency charged are also stored in `stripe_payments`.

#### Safety and failure

**7. What happens with no keys, or with an `sk_live_` key?**
`_payment_gateway(config)` in `app.py` decides this. If the keys are missing,
or the secret key starts with `sk_live_`, it logs the reason without any part of
the key and returns `None`, so the service has no gateway. Any payment request
then raises `PaymentsUnavailable`, which the routes turn into a 503.

The application still starts because a payment problem shouldn't take down
unrelated features. Animal profiles, homepage counters and staff tools keep
working, and only card donations are switched off. This is the same fail-closed
approach as `ADMIN_PASSWORD`, and it meets the requirement that the app starts
without anyone needing to step in.

**8. Gaps A and B: what happens, and why does the webhook still answer 200?**

- **Gap A, the earmarked animal no longer exists:** the donation is still
  recorded and a warning is logged for staff. The money has been received, and
  losing the record of a real donation would be worse than an earmark that no
  longer points anywhere.
- **Gap B, the charge can't be expressed in fils, or the amount or purpose is
  invalid:** nothing is recorded, the outcome is `NEEDS_RECONCILIATION`, and
  only the session ID is logged. Staff can look up that session in the Stripe
  dashboard and settle it manually.

Both answer 200 because an error response tells Stripe to try again, and Stripe
keeps retrying for days. Retrying can't fix either case, since the same event
would hit the same problem every time. A 200 means "received and handled," and
the problem goes to staff through the log instead of an endless retry loop.

**9. Why build the success and cancel URLs from `PUBLIC_BASE_URL` and never
from the Host header?**
The Host header comes from whoever sends the request, so an attacker can set it
to anything. If the server built return addresses from it, an attacker could
create a checkout session whose return address was their own site. A donor sent
there after paying could see a fake "payment failed, please re-enter your card"
page. `PUBLIC_BASE_URL` is fixed by whoever runs the server, so donors can only
ever return to the real site. If it's invalid, payments are switched off rather
than falling back to the header.

#### Design

**10. Where is the Adapter, what does it translate, and why does the Protocol
live in `service.py`?**
The Adapter is `StripeGateway` in `payments.py`. It converts between two
interfaces that don't match. The service expects a `PaymentGateway` with
`create_checkout` and `verify_event` that speak in fils and in our own
dataclasses. Stripe's library offers `stripe.checkout.Session.create` and
`stripe.Webhook.construct_event`, which speak in US cents and Stripe objects.
The adapter translates:

- **calls:** our two methods become Stripe's functions;
- **data:** Stripe objects become `CheckoutSession` and `PaymentConfirmed`;
- **units:** fils become cents and back again, at the peg;
- **errors:** Stripe's exceptions become `PaymentProviderError` and
  `InvalidWebhookSignature`.

`AnimalDirectoryAdapter` from 30 September is a second, separate Adapter.

The Protocol lives in `service.py` because of Dependency Inversion: the code
that uses an interface should own it. If the Protocol lived in `payments.py`,
the service would have to import `payments.py`, which imports Stripe. The
business rules would then depend on Stripe, which is exactly backwards. As
built, the service depends on nothing outside itself, and the Stripe adapter
depends on the service's contract.

**11. If the rescue switched to PayTabs, what would change and what would stay
untouched?**

What changes:

- A new `PayTabsGateway` class implementing `create_checkout` and
  `verify_event`. PayTabs can probably charge in JOD directly, which would
  remove the peg conversion.
- One change in `app.py`, so `_payment_gateway` builds the PayTabs gateway.

Where the code is still tied to Stripe, to be honest about it:

- The configuration fields are named `stripe_secret_key` and
  `stripe_webhook_secret`. PayTabs uses different credentials (a server key and
  a profile ID), so new fields would be needed.
- The table is named `stripe_payments`. Its columns (`charged_amount_minor`,
  `charged_currency`) are general, but the name isn't, so it would need
  renaming or a parallel table.
- The webhook address is `/stripe/webhook`, and PayTabs signs its callbacks
  differently. The route would need a new path, and I'd need to check whether
  it reads Stripe's header name directly.

What stays untouched: `DonationService`, the models (`CheckoutSession`,
`PaymentConfirmed`, `ProviderCharge` were designed not to mention Stripe), the
ledger, the impact statistics and the animals domain. The business rules don't
change at all.

**12. Why is the fake gateway in the tests and not in production code?**
Production should never contain code that can approve a payment without real
money. If the fake shipped with the application, a configuration mistake could
switch it on and record donations that never happened. Keeping it in the tests
means it can't run in production. Because the service depends on the Protocol
rather than on Stripe, the tests can still pass the fake in without the
production code knowing it exists.

#### Frontend

**13. Why does reloading `/animals/1` work, while `/api/nope` stays a JSON 404?
Which function decides that?**
`_register_frontend_routes` in `app.py`. `/animals/1` isn't a file on the
server. It's a page that React Router draws inside the browser. When the page is
reloaded, the browser asks the server for `/animals/1` directly, so the server
answers any non-`/api` address it doesn't recognise with `index.html`. React
then loads and shows the right page.

Addresses starting with `/api` are excluded from that fallback. If `/api/nope`
returned `index.html`, the frontend's data code would receive a web page when it
expected JSON and fail confusingly. Returning a JSON 404 tells it clearly that
the endpoint doesn't exist.

**14. Why is the font bundled into the build instead of loaded from Google
Fonts?**

- **Privacy:** loading from Google sends every visitor's IP address to Google. A
  German court ruled in 2022 that this breached GDPR without consent, and the
  rescue has visitors from Europe as well as Jordan.
- **Self-containment:** the brief requires a single process that runs everything
  itself, so the site shouldn't depend on an outside service just to display its
  text.
- **Reliability and speed:** the font arrives from the same server as the page,
  with no extra connection, and it still works if Google is slow or blocked.

**15. Where will real animal photos come from, and what does a card show until
then?**
Staff will upload photos through a staff-only photo-upload endpoint, planned for
2 October. Until then, each card shows a hand-drawn portrait of the animal's
species from `art.jsx`, so the page never shows a broken image or an empty box.

## Prompt for 2026-09-29 (verbatim)

```text
Read CLAUDE.md and assignment_1.md before doing anything. Today is 2026-09-29.
Today has THREE steps, in this order. Each step gets its own branch. Do NOT run
git commit/push/gh yourself: write the files, show me the diff summary, and give
me the exact commands (branch, add, commit with full message and body, push,
gh pr create, gh pr merge --merge). Wait for me to confirm each step is merged
before starting the next.

────────────────────────────────────────
STEP 0: land the uncommitted admin-auth work first (branch: feat/admin-auth)
────────────────────────────────────────
I'm on main with uncommitted work that isn't on the schedule: security.py,
tests/conftest.py, tests/test_security.py, and changes to app.py, config.py,
README.md, CLAUDE.md (47 lines). The animal routes need require_admin, so this
lands first.
- Run `git status` and `git diff` and summarise what's actually there. Don't
  assume.
- Check require_admin: it reads ADMIN_PASSWORD at request time (not import
  time), fails closed with 503 when unset, returns 401 on a wrong or missing
  password, compares with hmac.compare_digest (constant time, not ==), never
  logs or echoes the password, and has no default value anywhere.
- Run pytest and show the output. Then give me the commands to move this work
  onto feat/admin-auth and merge it. Split it into 2–3 logical commits if that
  reads better (e.g. security module + tests / wiring into app & config / docs).

────────────────────────────────────────
STEP 1: scope change: Stripe (branch: chore/stripe-scope)
────────────────────────────────────────
My professor has now asked me to integrate Stripe as well, so I can show more
SOLID and design-pattern work. This reverses a decision in CLAUDE.md. Before
editing, tell me every place this conflicts with CLAUDE.md or assignment_1.md.
At minimum:
  (a) "Stripe is out of scope" and ADR-5 = Stripe. ADR-5 needs a new subject.
      Propose 2–3 candidates (e.g. user accounts / per-staff login, email
      notifications, recurring donations) and recommend one.
  (b) "Every write endpoint gets @require_admin". The Stripe webhook can't send
      the admin password. It must be authenticated by Stripe's signature
      instead. Propose the exact wording of that exception.
  (c) Dependency count: `stripe` makes it 9 of 12. Use Stripe Checkout
      (redirect), so there's no frontend npm dependency.
Then edit CLAUDE.md only (no Stripe code today):
- Replace the "Stripe is out of scope" section with a "Payments (Stripe)"
  section: test mode only; STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET from
  env; unset means the payment endpoints fail closed with 503 (same philosophy
  as ADMIN_PASSWORD); refuse to start or refuse to charge if the key starts
  with sk_live_; never commit keys; never log them.
- Design constraints for later: Stripe lives inside domains/donations/ behind a
  PaymentGateway interface (Adapter pattern, Dependency Inversion). The service
  depends on the interface. The Stripe adapter and a fake adapter for tests
  both implement it, chosen in create_app. The ledger stays append-only: a
  donation row is written ONLY by the verified webhook
  (checkout.session.completed), never from the browser redirect or from a
  client-supplied amount. It is made idempotent by a UNIQUE Stripe
  session/event id so replayed webhooks don't double-count. The amount comes
  from the server, not the client.
- Add it to the schedule/plan in CLAUDE.md as its own future branch
  (feat/stripe-donations), after the donations ledger branch.
- Update the ADR-5 line to the new subject once I pick it.
Give me the commit commands. The message should explain why the scope changed
(professor's request, to demonstrate Adapter/DIP), not just "update CLAUDE.md".

────────────────────────────────────────
STEP 2: feat/animal-intake-adoption (today's scheduled work)
────────────────────────────────────────
1. domains/animals/models.py: Animal entity (name, species, breed, intake
   date) plus medical/vaccination history records, and a PlacementStatus enum:
   AVAILABLE, FOSTERING, PENDING, ADOPTED. Use frozen dataclasses where it
   makes sense, and the enum everywhere. No bare status strings outside
   models.py.
2. domains/animals/repository.py: the ONLY file that runs SQL for animals,
   against the existing tables in db/schema.sql. If the schema is missing
   something (e.g. a status-history table), STOP and tell me rather than
   quietly changing it, because ADR-3 already documents the schema.
3. domains/animals/service.py: business rules, mainly guarded transitions.
   Before coding, show me this proposed transition table and let me confirm it:
     available → fostering   (placed with a foster)
     available → pending     (adoption application received)
     fostering → available   (foster returned the animal)
     fostering → pending     (foster or other applicant applies to adopt)
     pending   → available   (application withdrawn/rejected)
     pending   → adopted     (adoption finalised)
     adopted   → (terminal: nothing)
   Everything else (adopted → available, available → adopted, same-state moves)
   is rejected with a domain exception (e.g. IllegalTransition) whose message
   names both states.
4. domains/animals/routes.py: a Flask blueprint returning JSON. Every
   POST/PUT/PATCH/DELETE has @require_admin. Wire it in create_app.
5. tests/test_animals_service.py: parametrize over ALL 16 (from, to) pairs,
   so every allowed transition succeeds and every rejected one raises. Also
   cover validation and not-found.
6. ADR-2 in ADR.md: how the domains stay independently modularizable. Use
   the exact format from assignment_1.md section 5 (Context / Decision /
   Alternatives considered / Consequences). Only ADR-2. Don't touch 1 or 3,
   and don't write 4 or 5.

SOLID: apply where it genuinely fits, and tell me in one line per item where it
shows up so I can defend it:
- SRP: routes parse the request, call the service and serialise; the service
  holds the rules; the repository holds the SQL. No business logic or SQL in
  routes.py.
- DIP: the service depends on an AnimalRepository Protocol (typing.Protocol),
  not on sqlite3. The concrete repository is injected in create_app (the
  composition root). Tests use either an in-memory SQLite repository or a
  fake, which must honour the same contract (LSP).
- ISP: keep the repository interface small, only the methods the service
  actually calls.
- OCP: allowed transitions are a data table (dict[Status, frozenset[Status]]),
  so adding a state means editing one table, not an if/elif chain.
- Patterns: I expect Repository and DI at the composition root. Do NOT force
  State/Strategy onto the transitions. A lookup table is clearer, and I'll
  justify that choice. If you think a pattern genuinely fits somewhere, say
  why before using it.

Code smells to avoid: primitive obsession (status as strings), magic strings
and numbers, fat route handlers, a god service, sqlite3.Row leaking out of the
repository (map to dataclasses), duplicated validation between routes and
service, long parameter lists (pass a dataclass), bare `except Exception`, and
dead code or speculative abstractions.

Security and correctness:
- Parameterised queries only (`?` placeholders). No f-strings or `%` in SQL,
  ever.
- Make the status change race-safe: `UPDATE animals SET status=? WHERE id=?
  AND status=?` and check rowcount, so two staff clicking at once can't both
  win. The status change and any history row go in one transaction.
- `PRAGMA foreign_keys = ON` per connection.
- Validate input: required fields, length limits, ISO dates, no intake date in
  the future. Reject unknown fields.
- Map errors to status codes: validation 400, missing 404, illegal transition
  409, no admin password 503, wrong password 401. Return JSON error bodies with
  no stack traces or SQL in the response.
- Public GET endpoints must not expose internal medical notes unless we decide
  they should. Ask me.
- Module boundary: domains/animals must never import domains/donations. They
  refer to each other by primary-key value only. Add a small test that fails
  if that import ever appears, so I can point to it in ADR-2.

Hard constraints (from CLAUDE.md): bind 0.0.0.0, PORT default 8000, DATA_DIR
default ./data, schema applies itself on boot, no .env required, no Dockerfile
/ compose / .github/workflows / IaC, fewer than 12 dependencies, 15–50 files.
Don't split things into extra files unnecessarily.

Verify before you claim. Show me the actual output of:
- `pytest --cov` with the coverage % for domains/animals (service + models)
- `python app.py` starting, plus curl calls: list animals, create one without
  the admin header (expect 401), create one with it (201), a legal transition
  (200) and an illegal one (409)
- the file count and dependency count

Finally, give me the git commands for this branch as several commits that
follow the natural order (models → repository → service + tests → routes +
wiring → ADR-2), each with a message that explains what changed and why.
Merge with --merge, never --squash.
```

## Prompt for 2026-09-30 (verbatim)

```text
Read CLAUDE.md, assignment_1.md, ADR.md and db/schema.sql before doing anything.
Today is 2026-09-30. The schedule says: feat/donation-impact-ledger. This is the
second feature domain and the data behind the homepage counters (audit fix #1:
numbers computed from real data at request time, never hardcoded).

Git rules as always: do NOT run git commit/push/gh yourself. Write the files,
show me what changed, and give me the exact commands. First check `git status`:
confirm yesterday's animals branch is merged, main is clean and pulled, and then
branch feat/donation-impact-ledger from main. Merge with --merge, never --squash.

────────────────────────────────────────
BEFORE WRITING ANY CODE: confirm these decisions with me
────────────────────────────────────────
My recommendation comes first each time. List all of them back in one message,
tell me where any of them conflicts with CLAUDE.md, assignment_1.md, ADR-2 or
ADR-3, and wait for my answers.

1. Money over the API. Accept "amount_jod" as a STRING like "25.500", check it
   against ^\d{1,5}(\.\d{1,3})?$ BEFORE parsing with Decimal (so "1e3", "NaN",
   "Infinity", "-5", " 5" and "5.1234" are all rejected), then convert to
   integer amount_fils inside the model. Reject a JSON number (float) with a
   400 that says to send a string. Alternative: accept an integer amount_fils.
2. Upper limit per donation: 10,000 JOD, as a named constant
   (MAX_DONATION_FILS). Zero or less is rejected too.
3. Date received: optional received_on (ISO date), which can't be in the future
   and defaults to today. Check whether schema.sql already has this column. If
   not, STOP and tell me, because it's a schema change in ADR-3's territory.
4. The schema contradiction: the comment says "a correction is a new
   compensating row", but CHECK (amount_fils > 0) makes negative rows
   impossible. Recommended: no corrections today. Reword the comment to "mistakes
   are not yet correctable" and name it as a known gap in ADR-4. Alternative: a
   separate reversals table (a schema change and more scope). Optional extra:
   BEFORE UPDATE / BEFORE DELETE triggers so SQLite itself refuses to change a
   ledger row. Tell me if that's worth it or scope creep.
5. Checking earmarked animals: donations declares a one-method AnimalDirectory
   Protocol (exists(animal_id) -> bool). create_app adapts AnimalService to it
   with a small adapter at the composition root, inside neither domain package.
   That's the Adapter pattern, used where it genuinely fits, and exactly what
   ADR-2 promised. Tests use a tiny fake directory. The boundary test must stay
   green IN BOTH DIRECTIONS.
6. Homepage impact stats: total raised (all time), total per purpose, number of
   donations, and number of distinct animals helped through earmarked gifts. NO
   "number of donors", because donor_name is optional and the count would be
   dishonest.
7. "More than 300 pets found homes" is an adoption count, which belongs to the
   animals domain. Recommended: a small public GET /api/animals/stats (counts by
   status) in the animals domain, with the homepage calling both endpoints. Do
   NOT merge them in the backend, because that couples the domains. Ask me
   whether this is today's scope or goes with the frontend days.
8. Money in responses: return both amount_fils (integer) and amount_jod (string
   "25.500"), so the frontend never does currency arithmetic. Format with
   integer division and modulo on fils, never float.
9. Donor privacy: donor names appear ONLY in the staff list, never in /impact,
   logs or error messages.

────────────────────────────────────────
WHAT GETS BUILT, one commit per step
────────────────────────────────────────
1. domains/donations/models.py
   - Donation, NewDonation.from_payload(...), ImpactSummary (frozen dataclasses).
   - DonationPurpose enum: MEDICAL_FUND, FOOD_FUND, GENERAL. Its values must match
     the schema's CHECK constraint exactly. Add a test that proves they match, so
     the two can't drift apart.
   - Validation in the same style as NewAnimal.from_payload: unknown fields
     rejected, required fields, length limits (donor_name, note), dates, and the
     amount rules above. If this duplicates helpers from the animals domain, do
     NOT import across domains. Accept small duplication and tell me where it is
     (it's the price of the ADR-2 boundary, and I'll mention it).
2. domains/donations/repository.py
   - The only donations code that runs SQL: add, list and the aggregate queries.
   - NO update or delete methods at all. Append-only is enforced by the code's
     shape, not just promised. Add a test asserting these methods don't exist.
   - Aggregates use SUM/COUNT/GROUP BY with COALESCE(SUM(...), 0), so an empty
     ledger returns 0, not None. All three purposes appear in the per-purpose
     totals even when a purpose's total is 0.
   - Map rows to dataclasses. sqlite3.Row never leaves this file.
3. domains/donations/service.py + tests/test_donations_service.py
   - DonationService plus a DonationRepository Protocol defined HERE, owned by
     the consumer, the same Dependency Inversion as the animals domain.
   - Impact stats computed at request time from the ledger. Nothing cached,
     hardcoded or stored as a running total.
   - Inject "today" (a clock callable) instead of calling date.today() inside
     the service, so the future-date rule is testable without flaky tests.
     Decide and tell me whether "today" means Asia/Amman or UTC.
   - Tests: every validation rule (including the nasty amount strings), the
     10,000 JOD boundary (exactly at the limit, and 1 fil over), an earmark to a
     missing animal (via the fake directory), append-only, aggregates on an
     empty and on a mixed ledger, per-purpose totals, and distinct animals
     (two gifts to the same animal count once).
4. domains/donations/routes.py + wiring in create_app
   - POST /api/donations: @require_admin (staff record cash and bank
     transfers).
   - GET  /api/donations: @require_admin (donor names are private). Add a
     sensible limit/offset so it can't dump everything unbounded.
   - GET  /api/donations/impact: public, no donor data.
   - No business logic in the handlers. Errors: 400 for validation or a missing
     earmarked animal, 401/503 for auth, 405 for PUT/DELETE. JSON error bodies
     with no stack traces or SQL.
   - Wire DonationService, the SQLite repository and the AnimalDirectory adapter
     in create_app, the only place concrete classes are chosen.
5. Coverage run across both domains. Put the REAL number in README.md, marked
   provisional (final on Oct 4).
6. ADR-4 (testing approach) in the exact assignment_1.md section 5 format
   (Context / Decision / Alternatives considered / Consequences).
   - Prioritised: all 16 transition pairs, validation, the lost race
     (StaleRead), append-only, the aggregates.
   - Left thin, and why: routes.py is excluded from coverage, there are no real
     multi-threaded race tests, no frontend tests yet, Stripe will only ever be
     tested through the fake adapter, and there are no corrections/reversals
     (if decision 4 goes that way).
   - Don't touch ADR 1–3 except the schema comment from decision 4 if I approve
     it, and don't write ADR-5. Tell me the ADR commit dates after this lands
     (it should be 3 distinct dates: Sep 28, 29, 30).

────────────────────────────────────────
SOLID: tell me in one line each where it shows up, so I can defend it
────────────────────────────────────────
- SRP: models build and validate, the repository does SQL, the service holds
  rules and aggregates, routes do HTTP. Formatting money for JSON is one small
  function, not repeated in every handler.
- OCP: adding a fourth purpose means changing the enum + CHECK constraint, not
  if/elif chains. Per-purpose totals iterate the enum.
- LSP: the fake AnimalDirectory and the adapter over AnimalService must behave
  identically (bool in, bool out, no exceptions for "not found").
- ISP: AnimalDirectory has ONE method. The donations domain must not see the
  rest of AnimalService. DonationRepository lists only what the service uses.
- DIP: the service depends on its own Protocols. Concrete classes are injected
  in create_app.
- Patterns: Repository, Dependency Injection, Adapter (AnimalDirectory). Do not
  force anything else. If you think another pattern fits, argue it before
  writing it.

────────────────────────────────────────
CODE SMELLS to avoid
────────────────────────────────────────
Floats anywhere near money. Primitive obsession (purpose as bare strings,
amounts as unlabelled ints: name them *_fils). Magic numbers (10000, 1000
fils/JOD, 3 decimals: all named constants). Feature envy (the service reaching
into animals internals). A god service. Duplicated validation between routes
and models. date.today() hidden inside logic. Aggregates computed in Python
loops when SQL can do it. Bare `except Exception`. Speculative code for Stripe
today: leave a clean seam, don't build it.

────────────────────────────────────────
SECURITY and CORRECTNESS
────────────────────────────────────────
- Parameterised SQL only (`?` placeholders). No f-strings or `%` in SQL, even
  for ORDER BY or LIMIT.
- The amount regex runs before Decimal. Reject bools (True is an int in
  Python), floats, lists and nulls for every typed field.
- Donor names and notes: length-limited, stored as plain text, never logged.
  (React escapes them later. Note in the README that dangerouslySetInnerHTML is
  banned.)
- /impact must not leak individual donations. Aggregates only.
- Staff list: paginated, admin-only.
- ledger inserts go in a transaction. PRAGMA foreign_keys = ON if
  earmarked_animal_id has a foreign key. Tell me if it has none, since the
  domain split may mean the FK was deliberately left out.
- Hard constraints unchanged: bind 0.0.0.0, PORT default 8000, DATA_DIR default
  ./data, schema applies itself on boot, no .env required, no Dockerfile /
  compose / workflows / IaC, fewer than 12 dependencies, 15–50 files.

────────────────────────────────────────
VERIFY: show me the actual output, don't summarise it
────────────────────────────────────────
- pytest --cov=domains --cov-report=term-missing (per file and total, both
  domains).
- python app.py, then curl:
    /api/donations/impact on an empty ledger (all zeros, all three purposes);
    POST a donation without the password → 401, with it → 201;
    an invalid amount ("25.5555", "1e3", 25.5 as a number) → 400;
    an earmark to a missing animal → 400;
    /impact again, showing the new totals;
    PUT and DELETE on /api/donations/<id> → 405.
- The boundary test passing, plus the file count and dependency count.

────────────────────────────────────────
COMMITS: cadence matters
────────────────────────────────────────
Sep 29 holds 12 of 24 commits (50%, over the 40% cap), so today must be split
properly. Give me separate commits, each with a subject plus a body explaining
WHY:
  models → repository → service + tests → routes + wiring (+ adapter)
  → README coverage → ADR-4 (+ schema comment fix, if approved)
Then the PR and `gh pr merge --merge` commands.

Also remind me at the end: ADR-1 is dated 2026-09-25 but was committed Sep 28.
I need to be ready to explain that the decision was made on the 25th.
```

## Prompt for 2026-10-01 (verbatim)

```text
Read CLAUDE.md, assignment_1.md, ADR.md, AI_USAGE.md, db/schema.sql and the whole
domains/donations/ package before doing anything. Today is 2026-10-01.

Git rules as always: do NOT run git commit, push or gh yourself. Write the files,
show me what changed, and give me the exact commands with full commit messages
(subject + body explaining WHY). Merge with --merge, never --squash.

SECRETS RULE, which overrides everything else today: never ask me to paste a key,
never print, echo, log or write any value of STRIPE_SECRET_KEY or
STRIPE_WEBHOOK_SECRET. To check whether they're set, print only "set" / "not
set" and the prefix (sk_test_ / sk_live_ / whsec_), never more characters. If a
key ever appears in output, a file or a diff, stop and tell me so I can roll it.

════════════════════════════════════════
PART 0: start of session
════════════════════════════════════════
- Give me the commands: git checkout main, git pull, git checkout -b
  feat/stripe-donations. Check that yesterday's donations branch is merged and
  main is clean.
- Log this prompt word for word in AI_USAGE.md, in the usual format, as an
  uncommitted change. It goes into the separate docs/ai-usage commit in Part D,
  not into any feature commit.

════════════════════════════════════════
PART A: prep, NO commits
════════════════════════════════════════
I'm doing steps 1–5 myself: a Stripe test-mode account (registered in Spain), the
sk_test_ key set only in my PowerShell session, stripe login, `stripe listen
--forward-to localhost:8000/api/donations/stripe/webhook` with the whsec_ set
in $env:STRIPE_WEBHOOK_SECRET, then the CLI checkout sessions create test with
unit_amount=25500 and then 25505.
- Remind me of the exact test command. Don't run anything that needs the keys.
- When I paste the output, tell me in plain words:
  (1) does Stripe accept JOD on this account;
  (2) is unit_amount in fils (1 JOD = 1000);
  (3) must the last digit be 0 (25505 rejected?);
  (4) what minimum amount Stripe states.
  This settles decisions 3 and 9 below. If JOD is NOT accepted, STOP. We decide
  together, because a second currency would break the fils-only SUM in the
  ledger.

════════════════════════════════════════
DECISIONS: already made, restated so you can check them against the repo
════════════════════════════════════════
Tell me before coding if any of these conflicts with CLAUDE.md, assignment_1.md or
an existing ADR.
1.  ADR-5 = the regional-gateway decision: Stripe as a test-mode reference
    adapter, with PayTabs/HyperPay as the production path, deliberately not
    built. Written after the code works, dated 2026-10-01. Per-staff accounts
    stay argued in the README and move to the report as a second deliberate
    omission.
2.  Pattern claims: ONLY Adapter (StripeGateway, AnimalDirectoryAdapter), DIP and
    DI. Don't claim Strategy. See the pattern honesty table below.
3.  Currency: JOD, if the prep test passes.
4.  Purpose, earmark and optional donor name travel in Checkout session metadata
    and come back inside the signed event. No pending-sessions table.
5.  The ledger records the event's amount_total, NEVER the amount originally
    requested.
6.  "Payments unavailable" = a service check (gateway is None) that answers 503.
    No Null Object class.
7.  Success and cancel URLs are built from PUBLIC_BASE_URL, NEVER from the
    request's Host header (an attacker-controlled Host could redirect donors to
    a phishing page).
8.  Test the real StripeGateway too: verify_event with a locally HMAC-signed
    payload (no network), and create_checkout with stripe.checkout.Session.create
    monkeypatched. That makes ADR-4's "Stripe only through the fake" untrue, so
    fix that one sentence in ADR-4 and say in the commit body that it's a
    correction, not a backfill.
9.  MIN_CHECKOUT_FILS: a named constant set from Stripe's stated minimum. If
    Stripe requires JOD amounts divisible by 10, enforce that in the model
    (NewDonation / checkout validation) with a clear 400, not by letting Stripe
    fail.
10. Accepted risk: the public checkout endpoint can be spammed (rate limiting
    would need Redis, which is forbidden). No money moves without a card, and no
    ledger row without a verified payment. This goes in the report.
11. Donate page (Oct 2): card via Checkout, CliQ alias, and bank transfer (the
    last two recorded by staff). Use CLEARLY MARKED placeholders for the CliQ
    alias and bank details unless I give you the real ones.
12. Frontend today stops at the animal pages.

Two gaps I want you to raise with me, not decide silently:
- A: the earmarked animal can vanish between checkout and payment. The donor has
  already paid, so a 4xx/5xx would make Stripe retry forever and lose the
  record. My proposal: record the donation anyway and keep the earmark, or drop
  it to general and log a warning. Recommend one.
- B: the event's currency isn't jod, or amount_total is outside
  MIN..MAX_DONATION_FILS. Should we log a warning, return 200 and not record it,
  or record it anyway? Recommend one, keeping in mind money has already moved.

════════════════════════════════════════
PART B: feat/stripe-donations, 6 commits (7 if ADR-5 is separate)
════════════════════════════════════════
1. docs: move ADR-5 to the regional-gateway decision. CLAUDE.md ONLY: change
   the ADR-5 line and the Oct 3 schedule row from per-staff accounts to "Stripe
   as a test-mode reference adapter; PayTabs/HyperPay as the production path",
   and add that production-path sentence to the Payments section.
2. feat: read Stripe keys and PUBLIC_BASE_URL from the environment.
   config.py gets stripe_secret_key, stripe_webhook_secret and public_base_url.
   Secrets have NO defaults. Validate public_base_url (http(s) scheme, no
   trailing slash, no path tricks). Add stripe to requirements.txt, pinned to the
   exact version pip installed (show me `pip show stripe`), and update the
   README env table. Config's __repr__ must never print the secret values: use
   dataclass field(repr=False) or equivalent, and add a test for it.
3. feat: add PaymentGateway interface with Stripe and fake adapters.
   domains/donations/payments.py is the ONLY file that imports stripe (add a
   test that enforces this, like the boundary test).
   CheckoutSession(id, url) and PaymentConfirmed(session_id, amount_fils,
   purpose, earmarked_animal_id, donor_name) are our own frozen dataclasses. No
   Stripe object ever leaves this file. StripeGateway translates Stripe errors
   into our own domain exceptions.
4. feat: record paid Checkout sessions idempotently.
   A new table stripe_payments(session_id TEXT NOT NULL UNIQUE, donation_id
   INTEGER NOT NULL REFERENCES donations(id), recorded_at) via CREATE TABLE IF
   NOT EXISTS. One repository method inserts the donation row and the payment
   row in ONE transaction. A replayed session hits the UNIQUE constraint → roll
   back → report "already recorded", not an error. There's still no update or
   delete anywhere in the ledger. Note in the commit body that this is a schema
   change in ADR-3's territory.
5. feat: start checkout and confirm payments in the donation service, plus tests.
   - start_checkout(payload) reuses the existing amount, purpose and earmark
     rules (no duplicated validation), then calls the gateway. It writes NOTHING
     to the ledger.
   - confirm_payment(event) records the donation using the amount from the
     verified event.
   - FakeGateway tests: replay recorded once, unpaid session ignored, bad amount,
     missing earmark (per gap A), payments unavailable (gateway None → error the
     route turns into 503). Plus the real StripeGateway tests from decision 8.
6. feat: expose checkout and the signature-verified webhook.
   Routes, wiring in create_app, the 503 paths, route tests. ADR-5 last, in this
   commit or as a 7th, once the live run works.

WEBHOOK behaviour, fixed by CLAUDE.md, so check the code against every line:
- It reads raw request bytes (request.get_data()) BEFORE any JSON parsing,
  because the signature covers the exact bytes. Never request.json first.
- It verifies with stripe.Webhook.construct_event, using the default timestamp
  tolerance (replay protection).
- A missing or bad Stripe-Signature → 400, nothing written, nothing sensitive
  logged.
- It acts ONLY on checkout.session.completed with payment_status == "paid". Any
  other event → 200 and ignored, so Stripe stops retrying.
- Replay → 200 "already recorded", no second row.
- It is exempt from @require_admin (authenticated by signature instead), and so
  is POST /api/donations/checkout (donors are the public). These are the ONLY
  two exceptions. Comment both in the code, pointing at CLAUDE.md.
- /donate/thanks NEVER writes to the ledger and never trusts query parameters.

════════════════════════════════════════
SOLID: one line each saying where it shows up, so I can defend it
════════════════════════════════════════
- SRP: payments.py talks to Stripe, the repository does SQL, the service decides,
  routes do HTTP. The webhook route must not contain event-handling logic.
- OCP: adding PayTabs means a new PaymentGateway implementation plus one line in
  create_app, with ZERO edits to DonationService. Tell me whether that's
  literally true of the code.
- LSP: FakeGateway and StripeGateway return the same dataclasses and raise the
  same domain exceptions. The service can't tell them apart.
- ISP: PaymentGateway has only what the service calls (create_checkout,
  verify_event). There are no Stripe-specific methods on it.
- DIP: the service owns the PaymentGateway Protocol. The stripe SDK is a detail
  that is injected, never imported by the service.

════════════════════════════════════════
PATTERN HONESTY TABLE: include this in your final summary
════════════════════════════════════════
I'm assessed on creational, structural and behavioral patterns, but I must only
claim what's really there. For each category, tell me what the code actually
has and whether I may claim it:
- Structural: Adapter. StripeGateway adapts the Stripe SDK to PaymentGateway,
  and AnimalDirectoryAdapter adapts AnimalService to AnimalDirectory. CLAIM.
- Creational: create_app is Flask's "application factory", and NewDonation /
  NewAnimal.from_payload are named constructors. Tell me honestly whether either
  counts as GoF Factory Method (I believe not). Config read once at startup is
  NOT a Singleton class, so don't label it one.
- Behavioral: webhook handling that picks behaviour by event type is a
  conditional or dict dispatch, not Strategy or Command. Say so plainly.
If a GoF pattern would genuinely improve something here, argue it before
writing it. Don't add one to fill a category.

════════════════════════════════════════
CODE SMELLS to avoid
════════════════════════════════════════
Stripe types leaking past payments.py. Duplicated amount/purpose/earmark
validation between direct donations and checkout. Magic strings
("checkout.session.completed", "paid", "jod", metadata keys): named constants.
Floats anywhere near money (amount_total is already an integer, so keep it one).
The service reading os.environ directly (config goes through Config only). Bare
`except Exception` around Stripe calls: catch stripe.error.* specifically inside
payments.py. Speculative PayTabs code: leave the seam, don't build it. A
webhook handler that grows into a god function.

════════════════════════════════════════
SECURITY checklist: confirm each one in your summary
════════════════════════════════════════
- sk_live_ key → app still boots, payment endpoints return 503, and the log line
  says "live key refused" WITHOUT any part of the key.
- No keys set → 503 on both payment endpoints, and the rest of the site works.
- Secrets never in logs, error bodies, Config repr, test output or git. Check
  .gitignore covers any local env files.
- Webhook payloads and donor names are never logged in full.
- Metadata is set server-side only, from validated input. Respect Stripe's
  metadata limits (key count and value length) and truncate or reject donor
  names that exceed them.
- Checkout session: mode="payment", card only, currency and amount fixed on the
  server. The client never supplies a price ID or a currency.
- Success and cancel URLs come from PUBLIC_BASE_URL only (decision 7).
- Recorded amount = the event's amount_total (decision 5). Check the currency
  (gap B).
- Idempotency is enforced by the database (UNIQUE) plus the transaction, not by
  a check-then-insert race.
- Parameterised SQL only.
- The checkout endpoint accepts application/json only, with a request size
  limit (MAX_CONTENT_LENGTH).

════════════════════════════════════════
VERIFY: show the actual output
════════════════════════════════════════
- pytest --cov=domains --cov-report=term-missing (both domains + payments.py,
  per file and total).
- A live run with `stripe listen` running:
    POST /api/donations/checkout → Checkout URL (I pay with 4242 4242 4242 4242);
    the webhook arrives → exactly one ledger row → /impact changes;
    stripe events resend <event_id> → still one row;
    a forged signature (curl with a fake header) → 400;
    no keys → 503; sk_live_ dummy key → 503, and show the log line.
- The boundary test (both directions) and the "only payments.py imports stripe"
  test are green. Show the file count and dependency count.

════════════════════════════════════════
PART C: start feat/react-frontend (branch off main AFTER the Stripe branch
merges; the branch itself merges Oct 2). 3–4 commits today
════════════════════════════════════════
1. chore: add Vite + React build tooling at the repo root. package.json +
   lockfile + vite.config.js, output to static/dist, dev proxy /api →
   http://localhost:8000. Deps: react, react-dom, react-router-dom, vite,
   @vitejs/plugin-react (5), which makes 9 declared with stripe (under 12).
   NO manifest in any subfolder.
2. feat: serve the built frontend from Flask with a client-side routing
   fallback. /api/* is never swallowed: an unknown API path gives a JSON 404, not
   index.html. Unknown non-API paths → index.html. Serve files with
   send_from_directory only (no path traversal). A missing static/dist → a clear
   message, not a crash.
3. feat: add api client and router: frontend/src/main.jsx, App.jsx, api.js.
   api.js centralises fetch and error handling (one place, no fetch calls
   scattered through components).
4. feat: add animal list and detail pages: the public view only (vaccinations,
   no medical notes).
Frontend security: no dangerouslySetInnerHTML anywhere, and no secrets in the
frontend. Any VITE_ variable is PUBLIC and shipped to browsers, so Stripe keys
never go near Vite. Checkout is a redirect, so no publishable key is needed.
Don't split every button into its own file (the file count must stay ≤ 50).
Give me the push command for tonight even though it merges Oct 2 (GitHub
records push timestamps, not local dates).

════════════════════════════════════════
PART D: end of session
════════════════════════════════════════
- Ask me for my own-words explanation of today's work and add it to
  AI_USAGE.md. Don't write it for me.
- Then give me the commands for a separate branch/commit
  docs/ai-usage-2026-10-01 containing only AI_USAGE.md.
- Show me the commit count per day after today (target: ~10 commits + merges on
  Oct 1, ~46 total, no day above ~28%).

PRIORITY if we run short on time: the Stripe branch and its tests first, then
ADR-5, then the frontend commits.
```

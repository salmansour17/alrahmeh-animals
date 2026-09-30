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

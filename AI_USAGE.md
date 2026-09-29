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

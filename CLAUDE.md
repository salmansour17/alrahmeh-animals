# Project Instructions: Al-Rahmeh Association for Animals

This file is my standing brief to you. Read it at the start of every session and
follow it without asking me to re-explain any of it.

## What I'm building

A rebuild of the website of the Al-Rahmeh Association for Animals
(جمعية الرحمة للرفق بالحيوان), a small animal rescue in Jordan. This is a real
handover, not an exercise: I audited their live site for another course and I
intend to give them what we build.

Three things I found broken in that audit, which this rebuild must visibly fix:

1. The homepage impact counters ("More than 300 pets found homes...") are
   hardcoded in the HTML. Replace them with numbers computed from real data at
   request time.
2. The donation flow is buried and awkward. Surface it properly.
3. "Adopt Now" and "Foster Now" go to Google Forms with no backend. Replace them
   with a real workflow tied to actual animal records.

The governing specification is `assignment_1.md` in this repo. When my
instructions and that file disagree, tell me — don't silently pick one.

## Stack — decided, do not relitigate

- **Backend: Python 3.11+ with Flask 3.1.** No ORM; use the standard library's
  `sqlite3` directly. Reasoning is in ADR-1.
- **Storage: SQLite**, one file at `${DATA_DIR}/alrahmeh.db`.
- **Frontend: React, built with Vite**, compiled to `static/dist` and served by
  the same Flask process.
- **Tests: pytest + pytest-cov.**

Two dependency manifests, both at the repository root: `requirements.txt` and
`package.json`. This is a deliberate, approved exception to the one-manifest
rule in section 1a — the mitigation is that `static/dist` is committed, so Node
is a build-time tool only and is never needed to run the app. Never create a
manifest inside a subfolder.

**Auth: one shared admin password**, read from `ADMIN_PASSWORD` and checked by
`require_admin` in `security.py`. No users table, no sessions, no password
hashing — one shared secret is all this organisation needs, and it keeps ADR-1's
"no user accounts" reasoning literally true. Unset means the staff endpoints fail
closed with 503; never add a default password. Per-staff accounts are a
deliberate omission argued in the README and the report (not an ADR).

Every write endpoint in any domain gets `@require_admin`, with exactly four
exceptions. Two are in the Stripe payment flow: `POST /api/donations/checkout` is
public because donors are not staff; it validates the amount against
server-side bounds and writes nothing to the ledger. `POST
/api/donations/stripe/webhook` is authenticated by verifying the
`Stripe-Signature` header against `STRIPE_WEBHOOK_SECRET` over the raw request
body, and answers 400 to anything that fails. The third (added 2026-10-02) is
`POST /api/animals/<id>/requests`, the adoption and foster form that replaces
the Google Forms: applicants are the public. It only creates an open request and
never changes an animal's status; only a staff decision does that. The fourth
(also 2026-10-02) is `POST /api/enquiries`, the contact and volunteer form that
replaces the old site's contact form and volunteer Google Form; it only stores a
message for staff. Both public forms take JSON only, carry a honeypot, and keep
the sender's details staff-only and out of logs. No other write endpoint may be
unauthenticated.

**Staff portal** (decision reversed on 2026-10-02, it was "no staff pages"). The
organisation's own work happens off the website too: adoptions arranged in
person, donations in cash, by CliQ or by bank. A website that cannot record
those cannot show true totals, so staff get a portal at `/staff` in the React
app. It signs in with `ADMIN_PASSWORD`, held only in page memory (never in
localStorage or a cookie) and sent as the Authorization header by `api.js`; with
no cookie involved there is no cross-site request forgery to defend against.
It covers: adoption and foster requests, contact and volunteer messages,
recording offline donations and offline adoptions, and managing animals.

## Payments (Stripe)

Added 2026-09-29 at my professor's request, to demonstrate Adapter and
Dependency Inversion on a real external integration. It reverses the earlier
"Stripe is out of scope" decision. Built on its own branch,
`feat/stripe-donations`, after the donations ledger exists — never before.

- **Test mode only.** `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` come from
  the environment. Unset means the payment endpoints fail closed with 503, the
  same philosophy as `ADMIN_PASSWORD`; the rest of the site keeps working.
- **A key starting `sk_live_` refuses to charge**: the payment endpoints answer
  503 and log why. The app still boots — refusing to start would let a payment
  misconfiguration take the animal pages and counters down with it, which is the
  same unattended-deployment reasoning as the `PORT` fallback.
- **Never commit keys, never log them**, never echo them in a response.
- **Stripe Checkout (redirect)** only, so there is no frontend npm dependency.
  `stripe` is the only new package.
- **Shape:** Stripe lives inside `domains/donations/` behind a
  `PaymentGateway` interface (Adapter pattern, Dependency Inversion). The
  donations service depends on the interface; a Stripe adapter and a fake
  adapter for tests both implement it, and `create_app` chooses which.
- **The ledger stays append-only and server-authoritative.** A card donation row
  is written ONLY by the verified `checkout.session.completed` webhook — never
  from the browser redirect, never from a client-supplied amount. The amount
  recorded is the one in the verified Stripe event. Replayed webhooks must not
  double-count: idempotency comes from a UNIQUE Stripe session id.
- **Open schema question for that branch:** where the session id lives. Adding a
  column to `donations` would not reach an existing database, because
  `CREATE TABLE IF NOT EXISTS` never alters a table, and a migration step is
  forbidden. A separate table that creates itself on boot avoids that. Either
  way it changes what ADR-3 describes — stop and ask before editing
  `schema.sql`.
- **Stripe is the test-mode reference adapter; a regional gateway (PayTabs,
  HyperPay) is the production path** behind the same `PaymentGateway`. Stripe
  does not onboard businesses based in Jordan, so the rescue cannot go live on
  it. That regional adapter is deliberately not built (ADR-5): without sandbox
  credentials it could not be run or tested. At handover, switching provider
  means one new adapter class and one line in `create_app`.

## Hard constraints — never violate these

- Single process, single container. One `python app.py` starts everything.
- Bind `0.0.0.0`. Never `localhost` or `127.0.0.1`.
- Port from the `PORT` environment variable, default 8000.
- SQLite path from `DATA_DIR`, default `./data`.
- No interactive setup at startup: no `input()`, no wizard, no manual migration
  step. Schema applies itself with `CREATE TABLE IF NOT EXISTS` on boot.
- Fully configurable through environment variables. Never require a `.env` file
  to exist, and never make me edit source to reconfigure anything.
- Must start in a couple of seconds.
- **Never create** a `Dockerfile`, `docker-compose.yml`, anything under
  `.github/workflows/`, or any Terraform/Bicep/ARM file. These are explicitly
  forbidden and would cost me marks.
- No Redis, RabbitMQ, Celery, cron, or any external database, cache or queue.
- Keep declared dependencies under 12 across both manifests. Currently 11
  (flask, stripe, pillow, pytest, pytest-cov; react, react-dom,
  react-router-dom, @fontsource/nunito, vite, @vitejs/plugin-react).
- Keep the file count between 15 and 50, excluding lockfiles, `.venv` and
  `node_modules`. The assignment calls this rough guidance; the final count may
  land a couple over 50 once `static/dist` is committed, which I accepted on
  2026-10-01, and on 2026-10-02 I accepted a projected final count of 53, then
  about 63 once the enquiries domain, the staff portal and the pages carrying
  over the old site's content were added. The report must say why. Don't split
  every button into its own component file.

## The feature domains

Two required domains, plus a small third (`domains/enquiries/`, contact and
volunteer messages) added on 2026-10-02. All persist through SQLite. All must be
independently modularizable: no domain package imports another, and they
reference each other by primary-key value only. That boundary is the seam a later assignment would cut to split them into
separate services, and I have to be able to point at it.

**1. Animal intake and adoption** (`domains/animals/`)
Animal profiles: name, species, breed, intake date, medical and vaccination
history. A placement lifecycle with guarded transitions:
`available → fostering → pending → adopted`. Fostering is central to how this
organisation actually operates, so it is a first-class state, not an
afterthought.

Adoption and foster **requests** (`placement_requests`) are how the public asks,
and a staff decision on one is what moves an animal. Approving an adoption moves
it to `pending`, approving a foster request to `fostering`, always through
`check_transition`. At most one adoption is approved at a time. Declining an
open request changes only that request; declining the approved adoption (it
fell through) returns the animal to `available`, and backup requests stay open.
Reaching `adopted` declines every remaining open request. Each decision and the
status change it causes land in one transaction. Applicants' names, emails and
messages are staff-only and never logged.

**2. Donation and impact ledger** (`domains/donations/`)
Append-only donation records against a purpose: medical fund, food fund, or
general. Impact statistics derived from the ledger, which is what the homepage
counters read from. Rows arrive two ways: staff record cash and bank-transfer
donations through a `@require_admin` endpoint, and card donations are written
by the verified Stripe webhook (see Payments).

**Offline adoptions** (animals domain). Adoptions arranged entirely in person,
for animals never entered here or from before the site existed, are recorded by
staff as dated, append-only entries with a count. The homepage's "found homes"
figure is the adopted animals on record plus those entries: every part of it is
a record someone entered, never a number typed into configuration.

**3. Enquiries** (`domains/enquiries/`)
Contact and volunteer messages from the public, kept for staff, who mark each
one handled. Same four layers as the other domains.

## Repository layout

```
requirements.txt  package.json + lock  vite.config.js
README.md  ADR.md  AI_USAGE.md  pytest.ini  .coveragerc
app.py            entry point: python app.py
config.py         env-driven Config dataclass
db/               schema.sql, connection.py
domains/
  animals/        models.py repository.py service.py routes.py
  donations/      models.py repository.py service.py routes.py
  enquiries/      models.py repository.py service.py routes.py
                  payments.py  (StripeGateway adapter; the PaymentGateway Protocol
                  lives in service.py, the fake gateway in the tests)
frontend/src/     main.jsx App.jsx api.js pages/ components/ styles.css
static/dist/      committed build output
tests/            conftest.py, a service and a routes test file per domain,
                  test_payments.py, test_security.py, test_domain_boundary.py
docs/             report.md architecture.md schema.md
```

Within each domain: `models.py` holds entities and enums, `repository.py` is the
only thing that touches SQL, `service.py` holds business rules, `routes.py` is a
Flask blueprint returning JSON. Tests target `service.py` and `models.py`.
`.coveragerc` omits `routes.py` because section 4 asks for coverage of business
logic, not routing glue.

## How I want you to work

**Git — I do it, not you.** Write the files, then hand me the exact commands to
stage, commit and push, with the commit message written out. Do not run
`git commit`, `git push`, `gh pr create` or `gh pr merge` yourself unless I
explicitly ask in that message. I want to read every diff before it lands.

**One branch per feature, merged by pull request.** Never commit to `main`
directly. Branch names: `feat/`, `test/`, `docs/`, `chore/`. Merge with
`--merge`, never `--squash` — squashing destroys the commit cadence I'm graded
on. A domain branch may stay open across two days so that nothing reaches `main`
untested.

**Commit messages** describe what changed and why, with a body when the reason
isn't obvious from the subject. "Initial commit", "WIP", "update" and "fix" are
worthless to me.

**Verify before you claim.** Actually run the app, actually run the tests,
actually check the coverage number. Show me the output. Don't tell me something
works because it looks like it should.

**Explain things plainly.** If you're presenting me a choice, tell me what each
option means in concrete terms — what changes on disk, what it costs, what the
risk is — and give me your recommendation instead of a survey. Skip the jargon
unless you define it.

## Code quality

I'm assessed on SOLID and on design patterns (Singleton, Factory Method,
Builder, Adapter, Proxy, Facade, Observer, Strategy, Command). Apply them only
where they genuinely fit. A repository abstraction over SQLite is real
dependency inversion; guarded status transitions may or may not want Strategy.
**Forced patterns read as worse code, not better** — and I have to justify every
one of them from memory. If a plain function is clearer, write the plain
function.

Small single-purpose classes, dependency injection at the composition root
(`create_app`), no domain logic inside route handlers.

## Process deliverables — keep current, never backfill

These are 30% of the grade, more than the working features.

**`ADR.md`** — exactly 5 entries, no more. The format is fixed in
`assignment_1.md` section 5: Context / Decision / Alternatives considered /
Consequences. Entries must land across at least 3 different commit dates, as the
decisions are actually made. The five are: (1) backend framework, (2) how the
domains stay independently modularizable, (3) the SQLite schema decision, (4)
testing approach and what I left thin, (5) what I chose not to build: the
production Jordanian payment gateway — Stripe is built as a test-mode reference
adapter, PayTabs/HyperPay is the production path behind the same interface.

**`AI_USAGE.md`** — add a row every session. Fill in the date, tool, my actual
prompt, disposition, and what changed. **Leave the last column to me.** That
column is "in my own words, how this works", and it is the one thing I cannot
outsource — mark it `⚠️ TODO (me)` with a specific question I need to answer, and
remind me it's outstanding. Never write it for me.

**`AI_USAGE.md` gets its own commit, at the end of each session.** The file is
already tracked. Never include it in a feature branch's `git add` commands.
When a session's work is merged, I write my own-words column for that session,
and then you hand me a separate commit for `AI_USAGE.md` alone, on its own
`docs/` branch merged by pull request like everything else. Never tell me to run
`git add .` or `git add -A` — always name the files explicitly, so this file
can't be swept in by accident.

**Tests** — at least 70% coverage on the business logic of both domains,
measured with:

```
pytest --cov=domains --cov-report=term-missing
```

Report the real number in the README.

## Why the process matters more than the code

There is a closed-book written exam on this project: six short-answer questions,
no notes, no device, graded against what's actually in the repo. It multiplies my
subtotal rather than adding to it, so a weak showing there wipes out good work
everywhere else.

That changes what I need from you. Don't hand me code I can't account for. If
something is subtle — why `create_app()` takes a `Config` instead of reading the
environment itself, why a malformed `PORT` falls back instead of raising — say so
at the time, so I learn it while it's being written rather than the night before.

## Schedule

Deadline: **2026-10-04 23:59**. Requirement is 12+ commits across 6+ distinct
calendar days, no single day over 40% of the total, pushed to
`github.com/salmansour17/alrahmeh-animals`.

| Date | Branch | Lands |
|---|---|---|
| Sep 28 | `chore/project-scaffold`, `feat/sqlite-persistence` | scaffold, ADR-1, schema, connection layer, ADR-3 |
| Sep 29 | `feat/admin-auth`, `chore/stripe-scope`, `feat/animal-intake-adoption` | shared admin password, Stripe scope change, entity, repository, guarded transitions, tests, ADR-2 |
| Sep 30 | `feat/donation-impact-ledger` | ledger, impact stats, tests, coverage run, ADR-4 |
| Oct 1 | `feat/stripe-donations`, then `feat/react-frontend` | PaymentGateway + Stripe and fake adapters, checkout and verified webhook, idempotency, tests, ADR-5; then Vite at root, api client, router, animal pages |
| Oct 2 | `feat/react-frontend` | homepage counters, donate page (redirects to Stripe Checkout), bilingual header, committed build |
| Oct 3 | `docs/report-and-final-adrs` | architecture and schema diagrams, 4-5 page report (per-staff accounts argued there as a second deliberate omission) |
| Oct 4 | `chore/deployment-contract-check` | clean-clone verification, final README numbers |

If I fall behind, protect in this order: working domains and their tests first,
then the process documents, then Stripe, then the frontend. A thin frontend with
honest ADRs beats a polished one without them.

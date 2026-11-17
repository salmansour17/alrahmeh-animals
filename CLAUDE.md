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

## Where we are: Assignment 2

Assignment 1 (the monolith: one Flask process, SQLite, React served by Flask) was
submitted on 2026-10-04 and is what `main` holds at the start of Assignment 2.

Assignment 2 splits that monolith into three services, ships them in containers,
moves storage to SQL Server, and deploys to Azure through GitHub Actions and
Terraform. **The governing specification is the Assignment 2 brief**
(`C:\Users\ASUS\Downloads\Assignment_2.pdf`; section numbers below, like §1a,
refer to it). `assignment_1.md` still governs anything Assignment 2 doesn't
change. When my instructions and the brief disagree, tell me — don't silently
pick one.

Many rules in the Assignment 1 version of this file are reversed on purpose (no
Docker, single process, SQLite, root-only manifests, shared admin password). The
old rules are in the Git history; do not follow them.

## Architecture — decided 2026-11-17

**Three service containers, one per feature domain** (ADR-6). The brief's text
assumes two domains; this project has three, so it has three services. This is
settled — do not re-raise it or suggest merging enquiries into animals.

| Service | Folder | Owns |
|---|---|---|
| `animals` | `services/animals/` | animals, medical records, placement requests, status changes, offline adoptions, photos, **staff accounts** |
| `donations` | `services/donations/` | the donation ledger, Stripe payments, impact statistics |
| `enquiries` | `services/enquiries/` | contact and volunteer messages |

- **Database per service.** Each service has its own SQL Server database and
  its own login, with no access to the others' databases. No service reads
  another's tables; it asks over HTTP.
- **HTTP between services**, located by environment variable (`ANIMALS_URL`),
  never a hardcoded host or port. **Every outbound call has a timeout**
  (`ANIMALS_TIMEOUT_S`). Use the standard library (`urllib.request`) unless that
  gets genuinely awkward. Ask before adding `requests`.
- **The server-side cross-seam flow (§3) is the earmark check.** When a
  donation is earmarked for an animal, the donations service's `AnimalDirectory`
  calls `GET /api/animals/<id>` on the animals service. If animals is down or
  slow: **checkout** goes ahead with the earmark marked unverified and the
  webhook re-checks it when the payment lands (a donor is never turned away);
  **staff recording an offline donation** get a clear 503 asking them to retry.
  Never a stack trace or a hung request.
- **The second server-side flow is the name lookup.** When staff list
  donations, the donations service collects the page's distinct earmarked
  animal ids and fetches their names from the animals service in **one batch
  call** (a list-by-ids endpoint on animals, also in its OpenAPI file). Names
  are cached in memory for a few minutes. If animals is down, the list still
  loads with "#12 (name unavailable)". The cache is for display only: the
  earmark check always asks fresh.
- **Calls go one way only: donations → animals.** The animals service never
  calls another service. Anything animals' pages need from donations (such as
  money raised for one animal) is fetched by the browser. Don't add a call that
  breaks this.
- **The homepage counters stay client-side**: the UI calls each service's own
  stats endpoint and shows each counter independently, so one service being
  down blanks only its own counter.
- **Enquiries calls nobody, and nobody calls it** server-side. It only checks
  staff tokens locally.
- **Cross-seam references are plain IDs.** A foreign key across the seam
  becomes an integer column with no constraint. Integrity is enforced in code or
  deliberately not enforced, and ADR-7 says which.
- **Photos live in the animals database** (`VARBINARY(MAX)`), not on disk.
  A Container App's filesystem is wiped when it scales to zero, so anything
  written to local disk is lost.

## Stack

- **Backend: Python 3.11+ with Flask 3.1**, same as Assignment 1 (§1d forbids
  changing language). No ORM. Raw SQL ported to SQL Server's dialect (T-SQL)
  through **`pymssql`**.
- **Storage: SQL Server.** Locally, one `mcr.microsoft.com/mssql/server:2022-latest`
  container in compose holding one database per service (three); on Azure, one
  Azure SQL serverless database per service on one logical server. Each service reads
  `DATABASE_URL`.
- **Frontend: React + Vite in `ui/`**, built to static files and served by an
  Azure Storage static website. It is no longer served by Flask, and the build
  output is no longer committed (CI builds it).
- **Tests: pytest + pytest-cov**, against a real SQL Server (a GitHub Actions
  service container in CI, the compose container locally). Lint: **ruff**.
- **WSGI server: gunicorn** (proposed 2026-11-17, confirm). Flask's built-in
  server is for development only. Migrations run **before** gunicorn starts, in
  the container's start command, never inside a worker. That way several workers
  can't race to apply the same migration.

**Manifests:** one per service (`services/<name>/requirements.txt`) and one for
the UI (`ui/package.json`). This replaces Assignment 1's root-manifest rule
(§1a). Never put a manifest at the repository root. **Soft cap: about 12
third-party packages per service** (§1b). Pin exact versions (`==`), because the
Dockerfiles require pinned dependencies.

## Staff auth — per-staff accounts (reversed 2026-11-17)

The single shared `ADMIN_PASSWORD` is retired. Staff get their own accounts:

- A `staff` table in the **animals** service. Passwords are hashed with
  `werkzeug.security` and logins issue a token signed with `itsdangerous`. Both
  libraries already come with Flask, so this adds no new dependencies. Tokens
  expire.
- The **donations and enquiries services each check a token themselves** using
  the shared secret `TOKEN_SIGNING_KEY`, with no HTTP call. Staff can still
  record donations and read messages while the animals service is down. The cost
  is that a deactivated account keeps working until its token expires; ADR-6
  states this.
- **The first admin comes from environment secrets** (`STAFF_BOOTSTRAP_EMAIL`,
  `STAFF_BOOTSTRAP_PASSWORD`), and only when the `staff` table is empty. **Never a
  default password.** If the signing key is unset, staff endpoints fail closed
  with 503.
- In the UI the token is held **in page memory only** (never localStorage or a
  cookie) and sent as the `Authorization` header by `api.js`. No cookie, so there
  is no cross-site request forgery to defend against.

**Every write endpoint requires a staff token, with exactly four exceptions:**

1. `POST /api/donations/checkout`: public, because donors aren't staff. It
   validates the amount against server-side bounds and writes nothing to the
   ledger.
2. `POST /api/donations/stripe/webhook`: authenticated by checking the
   `Stripe-Signature` header against `STRIPE_WEBHOOK_SECRET` over the raw request
   body. Anything that fails gets a 400.
3. `POST /api/animals/<id>/requests`: the public adoption and foster form. It
   only creates an open request and never changes an animal's status.
4. `POST /api/enquiries`: the public contact and volunteer form. It only stores
   a message.

Both public forms take JSON only, carry a honeypot field, and keep the sender's
details staff-only and out of logs. Staff login itself is public by nature and
must not reveal whether an email exists.

**Staff portal** at `/staff` in the UI covers adoption and foster requests,
contact and volunteer messages, recording offline donations and adoptions,
managing animals, and now managing staff accounts.

## Payments (Stripe) — unchanged rules, new home

Stripe now lives inside the donations service. Every Assignment 1 rule still
holds:

- **Test mode only.** If `STRIPE_SECRET_KEY` or `STRIPE_WEBHOOK_SECRET` is
  unset, the payment endpoints fail closed with 503. A key starting `sk_live_`
  refuses to charge (503, logged), but the service still boots.
- **Never commit keys, never log them**, never echo them in a response. On Azure
  they are Container Apps secrets.
- Stripe Checkout (redirect) only. The success and cancel URLs point at the
  static website's origin (configuration, not hardcoded).
- Stripe sits behind the `PaymentGateway` interface (Adapter pattern, Dependency
  Inversion). The Stripe and fake adapters both implement it, and `create_app`
  chooses which.
- **The ledger is append-only and server-authoritative.** Card rows are written
  only by the verified `checkout.session.completed` webhook. A UNIQUE Stripe
  session id makes replayed webhooks harmless.
- Stripe is the test-mode reference adapter; PayTabs/HyperPay is the production
  path (ADR-5, still current).

## Hard constraints — never violate these

**Runtime**
- Bind `0.0.0.0`. Port from `PORT`, default 8000. A malformed `PORT` falls back
  to the default instead of crashing.
- Fully configurable through environment variables. Never require a `.env` file,
  never make me edit source to reconfigure anything. Every variable a service
  reads is listed in `system.yaml` with its default; secrets have no default.
- No interactive setup: no `input()`, no wizard.
- `GET /health` on every service: 200 `{"status":"ok","db":"ok","version":"<git sha>"}`
  when it can read **and write** its own database, 503 otherwise. It reflects only
  the service's own state, never the other service's.
- One log line per request to stdout: method, path, status, duration. Never log
  applicants' details, tokens, passwords or keys.
- **Cold starts are normal.** The database may be paused, and resuming takes up
  to a minute (error 40613 or a timeout). Connect with retries and backoff. The
  UI shows a clear "starting up, try again" state instead of a blank page.

**Database migrations (§4)**
- Numbered SQL files in `services/<name>/migrations/` (`001_init.sql`, …),
  applied in order on startup by our own small runner, recorded in a
  `schema_migrations` table. A second boot applies nothing.
- **Applied migrations are never edited.** Corrections go in a new file.
- **Never drop or recreate a table that holds data**, never recreate the database
  on deploy, never delete a volume to redeploy. Graders check the code for this.
- At least one migration must change a table that already holds data. **This
  must reach Azure only after the first deploy has data in it**, so the report
  can show before and after (§4.6).

**Containers**
- One Dockerfile per service, in its folder. No `COPY . .` (copy named paths
  only), no secrets or `.env` in the image, pinned base image and dependencies,
  runs as a non-root user.
- `docker-compose.yml` at the root: all three services, one SQL Server, a one-off
  service running the idempotent `db/init.sql` (databases and logins), and
  `nginx:alpine` serving `ui/` with the folder mounted (no Dockerfile for it).
  `docker compose up --build` must work from a clean clone.
- Exactly three service containers, one per domain, and nothing else. **No**
  gateway, frontend server or proxy container, no Redis, no message broker, no
  background workers, no Kubernetes (§1c). Anything we'd want from that list
  goes in ADR-10.

**CI/CD (§5), GitHub Actions in `.github/workflows/`**
- On every push and PR: install, lint, test each service, **fail below 70%
  coverage per service**, validate `system.yaml` against `system.schema.json` and
  each `openapi.yaml`, build every image, `terraform fmt -check` and
  `terraform validate`.
- On push to `main` only, and only if CI passed on that commit: push images to
  GHCR tagged with the commit SHA, `terraform apply`, build the UI with a
  generated `config.js` holding the service URLs, upload it to `$web`, then poll
  `/health` on every service and fail if any doesn't return 200 in time (allow
  for the database waking up).
- **CI never touches Azure SQL.** Every connection wakes it up and is billed.

**Azure (§7) — only these resources, all in `rg-<prefix>`**
- 1 Container Apps environment (Consumption plan) with 3 Container Apps:
  `min_replicas = 0`, `max_replicas = 1`, public HTTPS ingress, CORS restricted
  to the static website's origin.
- 1 logical SQL server (`<prefix>-sql`) with 3 serverless databases
  (`<prefix>-animals-db`, `<prefix>-donations-db`, `<prefix>-enquiries-db`),
  one login each, on the free offer: General
  Purpose, Gen5, 0.5–1 vCore, locally redundant backups. Firewall: allow Azure
  services only, and my own IP only while I need it.
- 1 storage account (`<prefix-without-hyphens>ui`) with static website hosting,
  where the 404 page is `index.html` so React Router's links work. A
  `tfstate` container in the same account holds Terraform's state.
- The user-assigned managed identity `<prefix>-github`, trusted through OIDC
  only for `main`, with Contributor on the resource group only.
- **Do not create any other Azure resource**, and nothing with a fixed monthly
  cost (no Front Door, Application Gateway, Azure Container Registry, Redis, App
  Service plan, VM). If you think we need one, stop and tell me; it has to be
  justified in ADR-8 and confirmed with my professor first.

**Infrastructure as code — Terraform, concrete and explicit**

My professor wants each deployment concern built as its own visible piece, not
handed to a one-command tool. **Never use** `az containerapp up`, `azd up`, or
any portal "deployment center" wizard. Each concern is its own Terraform
resource or block that I can point to:

| Concern | Where it lives |
|---|---|
| Firewall | `azurerm_mssql_firewall_rule`, per-service SQL logins, HTTPS-only ingress, CORS policy |
| Load balancing and scaling | Container Apps ingress, explicit HTTP scale rule, min 0 / max 1 replicas |
| Health | startup and readiness probes on `/health` in each container app |
| Caching | the donations service's in-memory cache of animal names; `Cache-Control` headers set when uploading the UI (hashed assets cached for a year, `index.html` never cached) |
| Secrets | Container Apps `secret` blocks fed from GitHub secrets, never plain env vars |

**The bootstrap is separate and documented**, because the pipeline identity has
Contributor only and cannot create the resource group, itself, or role
assignments. `infra/bootstrap/` holds the one-time commands (resource group,
managed identity and its OIDC trust, the storage account and its `tfstate`
container, the SQL logins in T-SQL, Reader access for my professor), and the
README walks through them. After the bootstrap, nothing is changed by hand in
the portal.

**Secrets — a leak is a graded incident**
- Never commit a secret: not in source, workflows, compose, Terraform variables
  files or Git history. Local passwords for compose come from my shell
  environment, not a committed file.
- If one is ever pushed: tell me immediately. Within 24 hours it gets rotated,
  the GitHub secret is updated, and the incident is recorded in the README. An
  unreported leak caps the grade at 40/100.

## Repository layout (target)

```
README.md  ADR.md  AI_USAGE.md  CLAUDE.md  assignment_1.md
docker-compose.yml   system.yaml   system.schema.json
.github/workflows/   ci.yml  cd.yml
db/init.sql          idempotent: databases + one login per service (compose)
infra/
  bootstrap/         one-time setup commands, documented in the README
  *.tf               environment, container apps, SQL server + databases, storage
services/
  animals/           Dockerfile requirements.txt openapi.yaml app.py config.py
                     migrate.py migrations/ db.py security.py
                     animals/ staff/   (models repository service routes)
                     tests/
  donations/         Dockerfile requirements.txt openapi.yaml app.py config.py
                     migrate.py migrations/ db.py security.py
                     donations/   (models repository service routes payments)
                     tests/
  enquiries/         Dockerfile requirements.txt openapi.yaml app.py config.py
                     migrate.py migrations/ db.py security.py
                     enquiries/   (models repository service routes)
                     tests/
ui/                  package.json + lock, vite.config.js, index.html, src/
docs/                report.pdf
```

Within each domain package: `models.py` holds entities and enums,
`repository.py` is the only thing that touches SQL, `service.py` holds business
rules, `routes.py` is a Flask blueprint returning JSON. Tests target `service.py`
and `models.py`; `.coveragerc` omits `routes.py`.

**Shared code between services is copied, not imported.** Small files such as
`migrate.py`, `db.py` and the token check exist once per service. A shared
package would tie the services back together, which is the coupling the
split removes. Keep these copies small, and say so in ADR-6.

## How I want you to work

**Git — I do it, not you.** Write the files, then hand me the exact commands to
stage, commit and push, with the commit message written out. Do not run
`git commit`, `git push`, `gh pr create` or `gh pr merge` yourself unless I
explicitly ask in that message. I want to read every diff before it lands.

**One branch per feature, merged by pull request.** Never commit to `main`
directly; CI must run on the PR before CD runs on `main`. Branch names: `feat/`,
`test/`, `docs/`, `chore/`. Merge with `--merge`, never `--squash`, because
squashing destroys the commit cadence I'm graded on.

**Commit messages** describe what changed and why, with a body when the reason
isn't obvious from the subject. "Initial commit", "WIP", "update" and "fix" are
worthless to me.

**Verify before you claim.** Actually run `docker compose up`, actually run the
tests, actually check the coverage number, actually curl `/health`. Show me the
output. Don't tell me something works because it looks like it should.

**Azure costs my credit.** Before any command that creates, changes or deletes
an Azure resource, tell me what it does and wait for my yes. Never connect to
the Azure SQL databases from tests.

**Explain things plainly.** If you're presenting me a choice, tell me what each
option means in concrete terms — what changes on disk, what it costs, what the
risk is — and give me your recommendation instead of a survey. Skip the jargon
unless you define it.

## Code quality

I'm assessed on SOLID and on design patterns (Singleton, Factory Method,
Builder, Adapter, Proxy, Facade, Observer, Strategy, Command). Apply them only
where they genuinely fit. The repository layer is real dependency inversion; the
cross-seam client behind an interface, with a stub in tests, is another.
**Forced patterns read as worse code, not better** — and I have to justify every
one of them from memory. If a plain function is clearer, write the plain
function.

Small single-purpose classes, dependency injection at the composition root
(`create_app`), no domain logic inside route handlers.

## Process deliverables — keep current, never backfill

Process evidence is 25% of the grade (§6).

**`ADR.md`** — entries 1–5 stay as written. Where a decision changed, set that
entry's status to `Superseded by [N]` and leave its text alone. Already known:
ADR-1 (sqlite3) and ADR-3 (SQLite schema) are superseded by ADR-7. Add **exactly
five** new entries, 6–10, in the same Context / Decision / Alternatives
considered / Consequences format, landing on **at least 3 different commit
dates**:

6. The split (written 2026-11-17): three services, what crosses the seams (the
   earmark check, the batched name lookup, the staff token), whether ADR-2 held.
7. Data and migrations: SQLite to one SQL Server database per service, integrity
   lost at the seam and how it's compensated, recovery plan for a bad migration.
8. Serverless hosting on Azure: resources and cost model, scale-to-zero effects
   (cold starts, database resume, retries, migrations with a single replica),
   what changes at 100x traffic.
9. Pipeline and testing: what CI gates on and why, how the cross-seam test works,
   what is deliberately not tested.
10. One thing deliberately not built, and when it would be worth building.

**`AI_USAGE.md`** — add a row every session: date, tool, my actual prompt,
disposition, what changed. **Leave the last column to me.** It's "in my own
words, how this works", and it's the one thing I can't outsource. Mark it
`⚠️ TODO (me)` with a specific question I need to answer, and remind me it's
outstanding. Never write it for me. **Infrastructure files count** (§6): every
Dockerfile, compose file, workflow and `.tf` file you produce gets a row, and the
TODO question must ask about a specific line in it.

**`AI_USAGE.md` gets its own commit, at the end of each session**, on its own
`docs/` branch merged by pull request, after I've written my column. Never
include it in a feature branch's `git add` commands. Never tell me to run
`git add .` or `git add -A` — always name the files explicitly.

**Tests** — at least 70% coverage per service (all three) on core logic, plus at least one
integration test across the seam (ADR-9 says whether it runs against compose or
a stub). Per service:

```
pytest --cov --cov-report=term-missing
```

Report the real numbers in the README.

**Evidence to capture as it happens, not afterwards** (the report needs all of
it): the migration log line and the data before and after on Azure; a successful
CD run on `main`; **one failed run and the commit that fixed it**; a screenshot
of what a user sees with one service stopped. When one of these moments happens,
tell me to save the link or screenshot.

## Why the process matters more than the code

There is a closed-book written comprehension check: no notes, no device, graded
against what's actually in the repo, and "any line" of the Dockerfiles, compose
file, workflows and Terraform may be asked about. It multiplies my subtotal, so a
weak showing there wipes out good work everywhere else.

So don't hand me code I can't account for. When something is subtle — why
migrations run before gunicorn, why the health check writes, why `max_replicas`
is 1, why the pipeline identity can't assign roles, why the 404 page is
`index.html` — say so at the time, so I learn it while it's being written rather
than the night before.

## Schedule

Deadline: **2026-11-22 23:59 (assumed, confirm)**. Requirement: 12+ new commits
across 6+ distinct calendar days, no single day over 40% of them, **pushed** each
day (push timestamps are checked) to `github.com/salmansour17/alrahmeh-animals`.
The graded commit is tagged `submission`, on `main`, and deployed.

| Date | Branches | Lands |
|---|---|---|
| Nov 17 | `chore/a2-groundwork`, `feat/split-services` | this file, schema copy, ADR-6; code moved into the three `services/` folders and `ui/` with no behaviour change; Azure bootstrap started |
| Nov 18 | `feat/sqlserver-migrations`, `feat/containers` | SQL Server port, migration runner, `001` per service, photos into the database; three Dockerfiles, compose, `db/init.sql`; ADR-7 |
| Nov 19 | `feat/ci`, `feat/terraform-cd` | CI gates; Terraform; CD; **first deploy with `001` and seed data**; ADR-8 |
| Nov 20 | `feat/cross-seam`, `feat/staff-accounts` | earmark check and batched name lookup over HTTP with timeout, name cache and designed failure; health, logs, integration test, OpenAPI, `system.yaml`; staff accounts shipped with **`002`**, which alters tables holding data (Azure evidence); ADR-9 |
| Nov 21 | `feat/ui-forms`, `feat/staff-portal` | contact and volunteer forms redone, staff account management, cold-start UI; ADR-10 |
| Nov 22 | `docs/a2-report`, `chore/submission` | diagrams, report, README, clean-clone check, `submission` tag |

If I fall behind, protect in this order: the split working end to end, then
migrations and CI/CD to Azure, then the process documents, then staff accounts,
then UI polish. Staff accounts and the redesigned forms are not required by the
brief, so they are the first things to cut.

# Al-Rahmeh Association for Animals

A rebuild of the website of [Al-Rahmeh Association for Animals](https://www.alrahmehforanimals.org/)
(جمعية الرحمة للرفق بالحيوان), a small animal rescue in Jordan: three small
services, one per feature domain, and a static website that calls them.

The live site presents adoption listings that are not backed by any record
system, impact counters whose numbers are written into the HTML by hand, and
"Adopt Now" and "Foster Now" buttons that lead to Google Forms. This rebuild
replaces all three: animals are real records with a tracked placement lifecycle,
the homepage counters are computed from records at request time, and adoption
and foster requests are tied to actual animals and decided by staff. It also
carries over everything else the old site offered except its news: the
rescue's story, volunteering, contact details and the gift shop.

## Feature domains

| Domain | Responsibility |
|---|---|
| **Animal intake & adoption** | Animal profiles (species, breed, intake date, medical history) and the placement lifecycle: available → fostering → pending → adopted. |
| **Donation & impact ledger** | Donations recorded against a purpose (medical fund, food fund, general), and the impact statistics derived from them. |
| **Enquiries** _(small third domain)_ | Contact and volunteer messages from the public, kept for staff. |

Each domain is its own service, in `services/<name>/`, with its own database
and its own dependency manifest (ADR-6). No service imports another's code, and
a test in each service fails if that ever changes. They refer to each other by
id only, and only one call crosses between them on the server: the donations
service asks the animals service whether an earmarked animal exists.

## Layout

| Folder | What it is | Port in Compose |
|---|---|---|
| `services/animals/` | Animal intake, the placement lifecycle, adoption and foster requests, offline adoptions, photos | 8001 |
| `services/donations/` | The donation ledger, Stripe card payments, impact figures | 8002 |
| `services/enquiries/` | Contact and volunteer messages | 8003 |
| `ui/` | The website: React, built by Vite into static files | 8080 |
| `db/init.sql` | Local setup: one database and one login per service | |

Each service has its own `requirements.txt`, `Dockerfile` and database, and
`ui/` has its own `package.json`; there is no manifest at the repository root.
Each service's tables are defined by the numbered files in its `migrations/`
folder (ADR-7).

## Requirements

- Docker Desktop, for the whole system
- Python 3.11 or newer and Node.js 20 or newer, only to run a service or the
  website outside Docker

## Running locally with Docker Compose

The whole system starts with one command. First set five passwords in your
shell; they are never written to a file in the repository, and Compose stops
with a message naming any that is missing. The three service passwords go
inside each service's `DATABASE_URL`, so use **letters and digits only**, 8 or
more characters with upper and lower case and a digit (SQL Server's rule).

PowerShell (each is typed at a prompt, so it is not saved in your history):

```powershell
$env:MSSQL_SA_PASSWORD     = Read-Host "SQL Server admin password"
$env:ANIMALS_DB_PASSWORD   = Read-Host "animals service database password"
$env:DONATIONS_DB_PASSWORD = Read-Host "donations service database password"
$env:ENQUIRIES_DB_PASSWORD = Read-Host "enquiries service database password"
$env:ADMIN_PASSWORD        = Read-Host "staff portal password"
docker compose up --build
```

Then open <http://localhost:8080>. What starts, in order:

1. `sqlserver`, one SQL Server for the three databases (its data is kept in a
   Docker volume between runs);
2. `db-init`, which runs `db/init.sql` once and exits: three databases and
   three logins, each login allowed into its own database only;
3. the three services, each built from its own Dockerfile. Each container runs
   its migrations (`python migrate.py`), then for animals the sample animals,
   then gunicorn; if the migrations fail, the web server never starts;
4. `ui-build`, which builds the website with the service addresses in
   `config.js` and exits, and `web`, a stock nginx serving that build.

Every `docker compose` command, even `ps` or `logs`, needs the five variables
set in that shell. `docker compose down` stops everything and keeps the data;
`docker compose down -v` also deletes it. Card donations stay off unless
`STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are set too.

To see partial failure, stop one service: `docker compose stop animals`. The
website then shows "Could not reach the server" on the animal pages and a dash
for the adoption counter, while the donation figures, the donate page and the
contact form keep working. `docker compose start animals` brings it back.
Screenshots are in `docs/evidence/`.

## Running a single service without Docker

A service needs a SQL Server database. With the Compose stack running, the
databases are there but not published to your machine; the simplest way is a
separate SQL Server for development:

```powershell
docker run -d --name alrahmeh-sql -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD=$env:MSSQL_SA_PASSWORD -p 1434:1433 mcr.microsoft.com/mssql/server:2022-latest
```

Create a database in it (any name), then, from the service's folder:

```powershell
pip install -r requirements.txt
$env:DATABASE_URL = "mssql://sa:$([uri]::EscapeDataString($env:MSSQL_SA_PASSWORD))@localhost:1434/animals_dev"
$env:PORT = 8001
python app.py
```

`python app.py` applies the migrations, adds the sample animals (animals only)
and serves with Flask's development server. For the website on its own,
`cd ui && npm ci && npm run dev` serves it on <http://localhost:5173> and
forwards each `/api/...` call to the service on 8001, 8002 or 8003
(`ui/vite.config.js`).

The donations service keeps working with the animals service stopped; only a
staff donation earmarked for an animal is refused, with a 503 asking to retry
(ADR-6).

## Configuration

Every setting is read from the environment at startup. No `.env` file is
required. `PORT`, `DATABASE_URL`, `CORS_ORIGINS`, `FLASK_DEBUG`, `WEB_WORKERS`,
`WEB_THREADS` and `ADMIN_PASSWORD` are read by every service; the rest by the one named.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | TCP port to listen on. Values that are not valid port numbers are ignored with a warning. |
| `DATABASE_URL` | _(none; required)_ | The service's own database: `mssql://USER:PASSWORD@HOST:PORT/DATABASE`, with `?encrypt=true` on Azure. A secret, so it has no default; a service will not start without it. |
| `CORS_ORIGINS` | _(none)_ | Website origins allowed to call the service from a browser, comma separated, e.g. `http://localhost:8080`. No wildcard; unset allows none. |
| `WEB_WORKERS` | `1` | gunicorn worker processes in the container. One, so the in-memory rate limits and name cache are shared by every request. |
| `WEB_THREADS` | `4` | Threads in that worker, serving requests side by side. |
| `SAMPLE_ANIMALS` | `1` | _(animals)_ When the database has no animals, add six sample animals at startup (via the same service as a staff intake) so the animal pages have something to show. `0` starts empty. Never adds to a database that already has animals. |
| `FLASK_DEBUG` | `0` | Set to `1` for the Flask reloader and tracebacks in development. |
| `ADMIN_PASSWORD` | _(unset)_ | Shared password for the staff-only endpoints. **Unset disables them**, returning 503 rather than allowing access. |
| `STRIPE_SECRET_KEY` | _(unset)_ | _(donations)_ Stripe **test-mode** secret key (`sk_test_…`). Unset, or a live `sk_live_…` key, disables card donations (503); the rest of the site keeps working. |
| `STRIPE_WEBHOOK_SECRET` | _(unset)_ | _(donations)_ Signing secret (`whsec_…`) used to verify that webhook calls really come from Stripe. Unset disables card donations. |
| `CLIQ_ALIAS` | _(unset)_ | _(donations)_ The rescue's CliQ alias, shown on the donate page as a way to give without a card. Unset hides it. |
| `BANK_NAME`, `BANK_IBAN`, `BANK_ACCOUNT_NAME` | _(unset)_ | _(donations)_ Bank-transfer details for the donate page. Shown only when at least the IBAN and account name are set. |
| `ANIMALS_URL` | `http://animals:8000` | _(donations)_ Where the animals service answers. The default is its Docker Compose name; outside Compose, e.g. `http://127.0.0.1:8001` (not `localhost`: on Windows, Python tries IPv6 first and waits about 2 s before falling back, past the 2-second earmark check). |
| `ANIMALS_TIMEOUT_S` | `2` | _(donations)_ Seconds before a call to the animals service is given up. Values outside (0, 60] fall back to the default. |
| `ANIMAL_NAMES_TTL_S` | `300` | _(donations)_ Seconds the staff list keeps an earmarked animal's name before asking the animals service again. Names only: the earmark check always asks live. Values outside 1-3600 fall back to the default. |
| `ANIMAL_NAMES_CACHE_SIZE` | `1000` | _(donations)_ Most animal names kept in memory; the oldest go first. Values outside 1-100000 fall back to the default. |
| `PUBLIC_BASE_URL` | `http://localhost:5173` | _(donations)_ The website's origin. Donors return here after paying. Must be a bare `http(s)://host[:port]`; anything else disables card donations. |

## Card donations (Stripe test mode)

**Without keys, card donations are switched off on purpose.** A plain
start of the donations service sets no Stripe keys, so the two payment
endpoints answer 503 and the donate page offers CliQ and bank
transfer instead. Everything else works. A site must never take payments with
keys it was not given; see ADR-5.

The card flow itself is tested without keys or network: `pytest` signs
Stripe-format webhooks locally with a dummy secret and runs the real Stripe
adapter against them. It was also verified by hand against Stripe's sandbox: a
USD 35.97 test payment recorded once as 25.503 JOD, a resent webhook answered
200 with no second row, and a forged signature was refused with 400.

**To try it yourself** (about ten minutes, with a free Stripe account in test mode):

1. Create an account at `dashboard.stripe.com/register`, switch to **test mode**
   (or a sandbox), and copy the secret key from **Developers → API keys**. It
   starts `sk_test_`. A live `sk_live_` key is refused.
2. Install the [Stripe CLI](https://github.com/stripe/stripe-cli/releases) and,
   in one window, forward Stripe's confirmations to the app:

   ```powershell
   $env:STRIPE_SECRET_KEY = Read-Host "Paste sk_test key"
   stripe listen --events checkout.session.completed --forward-to localhost:8002/api/donations/stripe/webhook --api-key $env:STRIPE_SECRET_KEY
   ```

   It prints a signing secret starting `whsec_`.
3. In a second window, start the donations service with both values (and the
   other services and the website as in "Running locally"):

   ```powershell
   $env:STRIPE_SECRET_KEY     = Read-Host "Paste sk_test key"
   $env:STRIPE_WEBHOOK_SECRET = Read-Host "Paste the whsec secret"
   docker compose up --build
   ```

   With both set, Compose passes them to the donations service. The CLI's
   `--forward-to` port 8002 is the donations service's port in Compose.

4. Open `http://localhost:8080/donate`, choose an amount and continue. Stripe's
   sandbox checkout opens; pay with card `4242 4242 4242 4242`, any future
   expiry date and any CVC. You return to the thank-you page, the CLI shows the
   confirmation with a 200, and the homepage total rises.

Card payments are charged in US dollars at the Central Bank of Jordan's fixed
rate, because a Stripe test account cannot charge Jordanian dinars; the ledger
records the dinar amount (ADR-5). On a real deployment the two keys go into the
host's environment and the webhook address is registered once in the Stripe
dashboard instead of using `stripe listen`.

## Staff access

Admitting an animal, moving it through the placement lifecycle and recording a
donation are staff actions, protected by one shared password supplied as
`ADMIN_PASSWORD`, set to the same value for every service. Send it as the password half of an HTTP Basic credential; the
username is ignored, because there is one shared secret rather than a set of
accounts.

```powershell
$env:ADMIN_PASSWORD = Read-Host "Choose a staff password"   # typed at a prompt, so not saved in shell history
# then start each service from this window, as in "Running locally"
```

Staff then sign in at **`/staff`**, the staff portal, with that password. It is
kept only in the page's memory while the tab is open, never in the browser's
storage or a cookie. The portal covers adoption and foster requests, contact and
volunteer messages, recording donations received offline and adoptions arranged
offline, and managing animals (admitting, status, medical records, photos and
the public profile).

There is deliberately no default password and no fallback. With `ADMIN_PASSWORD`
unset, the staff endpoints answer 503 and the public site continues to work, so
a deployment that forgets to configure the secret is locked rather than exposed.

This is not a user-account system, and it is not meant to be: two members of
staff share one credential. The limitations are real and worth stating — no
per-person audit trail, no way to revoke one person's access without changing the
password for everyone, and the secret travels in a header, so it depends on HTTPS
in front of the app. For an organisation this size those were acceptable trades
against maintaining a users table that serves neither feature domain.

### Staff tasks without the portal

Every portal action is an ordinary staff-only API call, so each can also be done
from PowerShell. Run this once in the window where `ADMIN_PASSWORD` is set; it
reads the password from the environment, so it never appears in a command:

```powershell
$auth = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("staff:$env:ADMIN_PASSWORD")) }
$api = "http://localhost:5173/api"   # with `npm run dev`, which forwards each call to its service; under Compose, use each service's own port (8001 animals and requests, 8002 donations, 8003 enquiries)
function Send($method, $path, $body) { Invoke-RestMethod -Method $method "$api$path" -Headers $auth -ContentType "application/json" -Body ($body | ConvertTo-Json) }
```

| Task | Command |
|---|---|
| Admit an animal | `Send Post /animals @{ name = "Zaytoon"; species = "Dog"; breed = "Canaan Dog"; intake_date = "2026-09-01" }` |
| Move it through the lifecycle | `Send Post /animals/1/transitions @{ to = "fostering" }` |
| Add a vaccination | `Send Post /animals/1/medical-records @{ record_type = "vaccination"; description = "Rabies"; occurred_on = "2026-09-05" }` |
| Set its public profile | `Send Put /animals/1/profile @{ born_on = "2025-04-10"; colour = "Sandy gold"; personality = "Gentle"; weight_kg = "18.5"; about = "Loves long walks." }` |
| Upload a photo | `Invoke-RestMethod -Method Put "$api/animals/1/photo" -Headers $auth -ContentType "image/jpeg" -InFile .\zaytoon.jpg` |
| See open adoption and foster requests | `(Invoke-RestMethod "$api/requests?status=open" -Headers $auth).requests` |
| Approve or decline one | `Send Post /requests/3/decision @{ outcome = "approved" }` |
| Read new messages | `(Invoke-RestMethod "$api/enquiries?handled=false" -Headers $auth).enquiries` |
| Mark a message handled | `Send Post /enquiries/2/handled @{}` |
| Record a cash, CliQ or bank donation | `Send Post /donations @{ amount_jod = "25.500"; purpose = "food_fund"; received_on = "2026-10-01" }` |
| Record adoptions arranged offline | `Send Post /animals/offline-adoptions @{ animal_count = 300; adopted_on = "2025-12-31"; note = "January 2018 to December 2025" }` |
| List recent donations | `(Invoke-RestMethod "$api/donations?limit=20" -Headers $auth).donations` |

## Website

The React app lives in `ui/` and is built by Vite into `ui/dist`, plain static
files. The build is not committed. Where each service lives is configuration:
`ui/public/config.js` is loaded before the app, and the deployment replaces it
with the real addresses. Locally its addresses are empty, so calls stay on the
dev server and are forwarded.

```bash
cd ui
npm ci            # once, installs the exact versions in package-lock.json
npm run dev       # live-reloading site on http://localhost:5173, with the three services running
npm run build     # static files in ui/dist
```

The visual design follows three reference designs the project owner supplied:
a peach-to-sage hero with tilted tags, a paw-shaped hero whose toes show
adoptable animals and link to their profiles, and an arch-shaped profile with
PREV and NEXT. The logo is the rescue's own, recoloured blue.

## Tests

Each service is tested on its own, from its own folder, against a real SQL
Server. Each run creates its own database with a random name, applies the
service's migrations to it, empties the tables before every test, and drops
the database at the end, so no test touches a real database. Point the tests
at a SQL Server with `MSSQL_SA_PASSWORD` (for one on `localhost:1433`) or
`TEST_SQLSERVER_URL` (any host and port):

```powershell
$env:TEST_SQLSERVER_URL = "mssql://sa:$([uri]::EscapeDataString($env:MSSQL_SA_PASSWORD))@localhost:1434/master"
cd services/animals;   pytest --cov --cov-report=term-missing
cd ../donations;       pytest --cov --cov-report=term-missing
cd ../enquiries;       pytest --cov --cov-report=term-missing
```

Coverage is measured on each service's domain package and excludes Flask
blueprints (`routes.py`), which are routing glue rather than business logic.
Besides the domain rules, each service tests its migration runner (a second
run applies nothing, an edited migration stops the start, a failed migration
leaves no trace, no migration drops anything), the connection retry, and CORS.
The donations tests check the call to the animals service over real HTTP,
against a stand-in served on a random local port (`tests/animals_stub.py`).

Coverage on SQL Server, measured 2026-11-18:

| Service | Tests | Domain coverage |
|---|---|---|
| animals | 243 passed | 100% |
| donations | 234 passed | 100% |
| enquiries | 78 passed | 100% |

### Clean-clone check of the Assignment 1 monolith (2026-10-04)

A fresh `git clone` from GitHub into an empty folder, a new virtual
environment, `pip install -r requirements.txt` and `python app.py`, with no
configuration except `PORT=8765`, so it could not clash with a copy on 8000:

- Ready in 1.8 s, listening on `0.0.0.0`. The schema created itself and
  `data/alrahmeh.db` appeared; there was no prompt and no manual step.
- No Node, no `node_modules` and no `.env` file: the committed `static/dist`
  served the homepage, `/animals`, `/donate` and `/staff` (all 200).
- `GET /api/donations/impact` answered 200 with zeroed totals, computed from
  the empty ledger.
- `POST /api/donations/checkout` answered 503 and the log said why: without
  Stripe keys, card donations stay off and the rest of the site works.
- `pytest --cov=domains` in the clone: every test passed, 100%.

100% line coverage says every line ran, not that every case is covered; ADR-4
records what the tests deliberately leave thin.

## Pre-commit hooks

Two checks run on your machine before each commit (`.pre-commit-config.yaml`):
ruff lints and formats the Python, and gitleaks refuses a commit that contains
something that looks like a secret. CI runs the same checks again, so the hooks
only save a round trip; they are not the safety net.

```bash
pip install pre-commit
pre-commit install            # once per clone: runs the hooks on every commit
pre-commit run --all-files    # run them on everything, e.g. after changing the config
```

## API

| Endpoint | Access | Purpose |
|---|---|---|
| `GET /api/animals` | public | List animals (`?status=` to filter) |
| `GET /api/animals/<id>` | public | One animal, with vaccinations only |
| `GET /api/animals/stats` | public | Animals per placement status (homepage "found homes") |
| `GET /api/animals/<id>/staff` | staff | Full record: notes, medical history, status history |
| `POST /api/animals` | staff | Admit an animal |
| `POST /api/animals/<id>/transitions` | staff | Move through the placement lifecycle |
| `POST /api/animals/<id>/medical-records` | staff | Add a medical record |
| `PUT /api/animals/<id>/profile` | staff | Set the public profile: age, colour, personality, weight, about |
| `GET /api/animals/<id>/photo` | public | The animal's photo (WebP, metadata stripped) |
| `PUT /api/animals/<id>/photo` | staff | Upload a photo (JPEG, PNG or WebP, up to 10 MB) |
| `POST /api/animals/<id>/requests` | public | Ask to adopt or foster this animal |
| `GET /api/requests` | staff | Adoption and foster requests (`?status=open`) |
| `POST /api/requests/<id>/decision` | staff | Approve or decline a request |
| `GET /api/animals/offline-adoptions` | staff | Adoptions recorded from outside the site |
| `POST /api/animals/offline-adoptions` | staff | Record adoptions arranged offline |
| `GET /api/donations/impact` | public | Homepage totals, aggregates only |
| `GET /api/donations` | staff | Donations, newest first (`?limit=`, max 200, `?offset=`) |
| `GET /api/donations/<id>` | staff | One donation |
| `POST /api/donations` | staff | Record a cash or bank-transfer donation |
| `POST /api/donations/checkout` | public | Start a card donation (Stripe Checkout) |
| `POST /api/donations/stripe/webhook` | Stripe-signed | Stripe confirms a payment |
| `GET /api/donations/offline-methods` | public | CliQ and bank details, if configured |
| `POST /api/enquiries` | public | Send a contact or volunteer message |
| `GET /api/enquiries` | staff | Messages (`?handled=false`) |
| `POST /api/enquiries/<id>/handled` | staff | Mark a message handled |
| `GET /health` | public | Every service. 200 `{"status": "ok", "db": "ok", "version": "<git sha>"}` when the service can read and write its own database, 503 with `"status": "error"` otherwise |
| `GET /api/meta/schema` | staff | Tables present, to confirm the schema applied itself |

Amounts are sent as a string of Jordanian dinars, `"amount_jod": "25.500"`,
never as a JSON number, and come back both as `amount_fils` (an integer) and as
that string. Donations cannot be edited or deleted: those requests answer 405,
and the database refuses them too.

**Frontend rule:** donor names, animal names and notes are user-supplied text.
They are rendered only through React's normal escaping; `dangerouslySetInnerHTML`
is banned in this codebase.

## Project documents

- [`ADR.md`](ADR.md) — architecture decision record
- [`AI_USAGE.md`](AI_USAGE.md) — log of AI assistance
- [`docs/report.pdf`](docs/report.pdf) — the report: SDLC discussion, architecture and schema diagrams

## Contact

Al-Rahmeh Association for Animals — admin@alrahmeh.org ·
[Facebook](https://facebook.com/Rahmehforanimals) ·
[Instagram](https://instagram.com/rahmehforanimals)

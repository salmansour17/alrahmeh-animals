# Al-Rahmeh Association for Animals

A rebuild of the website of [Al-Rahmeh Association for Animals](https://www.alrahmehforanimals.org/)
(جمعية الرحمة للرفق بالحيوان), a small animal rescue in Jordan, as a single-process
web application.

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

The domains share a database file but no code: no domain package imports
another, and they reference each other by primary key only. A test fails if
that ever changes.

## Approved deviation: two dependency manifests

Section 1a of the assignment permits a single dependency manifest at the repo
root. This project has two: `requirements.txt` for the Python process and
`package.json` for the React frontend. The instructor approved the use of React
for the user interface on 2026-09-25.

> _(instructor's approval, quoted here — to be filled in)_

Both manifests sit at the repository root; there are no per-folder manifests.
The Node toolchain is a build-time dependency only: `static/dist` is committed,
so a clone that installs `requirements.txt` and runs `python app.py` serves the
full application with Node absent from the machine.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer — **only** if you intend to modify the frontend. The
  compiled bundle is committed, so running the app needs Python alone.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The application serves on <http://0.0.0.0:8000> by default. No migration step,
interactive prompt or manual warm-up is needed: the schema is applied on
startup if it is not already present.

## Configuration

Every setting is read from the environment at startup, and every one has a
default. No `.env` file is required.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | TCP port to listen on. Values that are not valid port numbers are ignored with a warning. |
| `DATA_DIR` | `./data` | Directory holding the SQLite file and the `photos/` folder of animal photos. Both are created on startup if absent. |
| `FLASK_DEBUG` | `0` | Set to `1` for the Flask reloader and tracebacks. Leave unset in deployment. |
| `ADMIN_PASSWORD` | _(unset)_ | Shared password for the staff-only endpoints. **Unset disables them**, returning 503 rather than allowing access. |
| `STRIPE_SECRET_KEY` | _(unset)_ | Stripe **test-mode** secret key (`sk_test_…`). Unset, or a live `sk_live_…` key, disables card donations (503); the rest of the site keeps working. |
| `STRIPE_WEBHOOK_SECRET` | _(unset)_ | Signing secret (`whsec_…`) used to verify that webhook calls really come from Stripe. Unset disables card donations. |
| `CLIQ_ALIAS` | _(unset)_ | The rescue's CliQ alias, shown on the donate page as a way to give without a card. Unset hides it. |
| `BANK_NAME`, `BANK_IBAN`, `BANK_ACCOUNT_NAME` | _(unset)_ | Bank-transfer details for the donate page. Shown only when at least the IBAN and account name are set. Staff record these donations afterwards, like cash. |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | The site's own origin, e.g. `https://donate.example.org`. Donors return here after paying. Must be a bare `http(s)://host[:port]`; anything else disables card donations. |

The SQLite database lives at **`${DATA_DIR}/alrahmeh.db`**.

## Card donations (Stripe test mode)

**Without keys, card donations are switched off on purpose.** A plain
`python app.py`, which is what the deployment script runs, sets no Stripe keys,
so the two payment endpoints answer 503 and the donate page offers CliQ and bank
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
   stripe listen --events checkout.session.completed --forward-to localhost:8000/api/donations/stripe/webhook --api-key $env:STRIPE_SECRET_KEY
   ```

   It prints a signing secret starting `whsec_`.
3. In a second window, start the app with both values:

   ```powershell
   $env:STRIPE_SECRET_KEY     = Read-Host "Paste sk_test key"
   $env:STRIPE_WEBHOOK_SECRET = Read-Host "Paste the whsec secret"
   python app.py
   ```

4. Open `http://localhost:8000/donate`, choose an amount and continue. Stripe's
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
`ADMIN_PASSWORD`. Send it as the password half of an HTTP Basic credential; the
username is ignored, because there is one shared secret rather than a set of
accounts.

```powershell
$env:ADMIN_PASSWORD = Read-Host "Choose a staff password"   # typed at a prompt, so not saved in shell history
python app.py
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
$api = "http://localhost:8000/api"
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

## Frontend

The React app lives in `frontend/` and is built by Vite into `static/dist`,
which is committed, so running the site needs Python only. To change the
frontend:

```powershell
npm ci            # once, installs the exact versions in package-lock.json
npm run dev       # live-reloading preview on http://localhost:5173, with python app.py running for the API
npm run build     # rebuilds static/dist; commit it with the source change
```

The visual design follows three reference designs the project owner supplied:
a peach-to-sage hero with tilted tags, a paw-shaped hero whose toes show
adoptable animals and link to their profiles, and an arch-shaped profile with
PREV and NEXT. The logo is the rescue's own, recoloured blue.

## Tests

```bash
pytest --cov=domains --cov-report=term-missing
```

Coverage is measured against `domains/` and excludes Flask blueprints
(`routes.py`), which are routing glue rather than business logic. The
configuration lives in `.coveragerc`.

Final coverage, measured 2026-10-04:

```
Name                              Stmts   Miss  Cover
-----------------------------------------------------
domains/animals/models.py           242      0   100%
domains/animals/photos.py            68      0   100%
domains/animals/repository.py       116      0   100%
domains/animals/service.py          171      0   100%
domains/donations/models.py         160      0   100%
domains/donations/payments.py        67      0   100%
domains/donations/repository.py      43      0   100%
domains/donations/service.py         75      0   100%
domains/enquiries/models.py          89      0   100%
domains/enquiries/repository.py      25      0   100%
domains/enquiries/service.py         21      0   100%
-----------------------------------------------------
TOTAL                              1077      0   100%

398 passed
```

### Clean-clone check (2026-10-04)

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
- `pytest --cov=domains` in the clone: 398 passed, 100%.

100% line coverage says every line ran, not that every case is covered; ADR-4
records what the tests deliberately leave thin.

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
| `PUT /api/animals/<id>/photo` | staff | Upload a photo (JPEG, PNG or WebP, up to 2 MB) |
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

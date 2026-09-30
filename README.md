# Al-Rahmeh Association for Animals

A rebuild of the website of [Al-Rahmeh Association for Animals](https://www.alrahmehforanimals.org/)
(جمعية الرحمة للرفق بالحيوان), a small animal rescue in Jordan, as a single-process
web application.

The live site presents adoption listings that are not backed by any record
system and impact counters whose numbers are written into the HTML by hand.
This rebuild replaces both: animals are real records with a tracked placement
lifecycle, and the homepage counters are computed from the donation ledger at
request time.

## Feature domains

| Domain | Responsibility |
|---|---|
| **Animal intake & adoption** | Animal profiles (species, breed, intake date, medical history) and the placement lifecycle: available → fostering → pending → adopted. |
| **Donation & impact ledger** | Donations recorded against a purpose (medical fund, food fund, general), and the impact statistics derived from them. |

The two domains share a database file but no code: neither package imports the
other, and they reference each other by primary key only.

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
| `DATA_DIR` | `./data` | Directory holding the SQLite file. Created on startup if absent. |
| `FLASK_DEBUG` | `0` | Set to `1` for the Flask reloader and tracebacks. Leave unset in deployment. |
| `ADMIN_PASSWORD` | _(unset)_ | Shared password for the staff-only endpoints. **Unset disables them**, returning 503 rather than allowing access. |

The SQLite database lives at **`${DATA_DIR}/alrahmeh.db`**.

## Staff access

Admitting an animal, moving it through the placement lifecycle and recording a
donation are staff actions, protected by one shared password supplied as
`ADMIN_PASSWORD`. Send it as the password half of an HTTP Basic credential; the
username is ignored, because there is one shared secret rather than a set of
accounts.

```bash
ADMIN_PASSWORD=choose-something-long python app.py
curl -u staff:choose-something-long http://localhost:8000/api/meta/schema
```

There is deliberately no default password and no fallback. With `ADMIN_PASSWORD`
unset, the staff endpoints answer 503 and the public site continues to work, so
a deployment that forgets to configure the secret is locked rather than exposed.

This is not a user-account system, and it is not meant to be: two members of
staff share one credential. The limitations are real and worth stating — no
per-person audit trail, no way to revoke one person's access without changing the
password for everyone, and the secret travels in a header, so it depends on HTTPS
in front of the app. For an organisation this size those were acceptable trades
against maintaining a users table that serves neither feature domain.

## Tests

```bash
pytest --cov=domains --cov-report=term-missing
```

Coverage is measured against `domains/` and excludes Flask blueprints
(`routes.py`), which are routing glue rather than business logic. The
configuration lives in `.coveragerc`.

Current coverage (provisional, measured 2026-09-30; final figure on 2026-10-04):

```
Name                              Stmts   Miss  Cover
-----------------------------------------------------
domains/animals/models.py           114      0   100%
domains/animals/repository.py        53      0   100%
domains/animals/service.py           54      0   100%
domains/donations/models.py         120      0   100%
domains/donations/repository.py      30      0   100%
domains/donations/service.py         32      0   100%
-----------------------------------------------------
TOTAL                               403      0   100%

160 passed
```

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
| `GET /api/donations/impact` | public | Homepage totals, aggregates only |
| `GET /api/donations` | staff | Donations, newest first (`?limit=`, max 200, `?offset=`) |
| `GET /api/donations/<id>` | staff | One donation |
| `POST /api/donations` | staff | Record a cash or bank-transfer donation |

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
- [`docs/report.md`](docs/report.md) — SDLC discussion, architecture and schema diagrams

## Contact

Al-Rahmeh Association for Animals — admin@alrahmeh.org ·
[Facebook](https://facebook.com/Rahmehforanimals) ·
[Instagram](https://instagram.com/rahmehforanimals)

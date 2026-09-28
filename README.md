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

The SQLite database lives at **`${DATA_DIR}/alrahmeh.db`**.

## Tests

```bash
pytest --cov=domains --cov-report=term-missing
```

Coverage is measured against `domains/` and excludes Flask blueprints
(`routes.py`), which are routing glue rather than business logic. The
configuration lives in `.coveragerc`.

Current coverage: _to be reported once both domains are implemented._

## Project documents

- [`ADR.md`](ADR.md) — architecture decision record
- [`AI_USAGE.md`](AI_USAGE.md) — log of AI assistance
- [`docs/report.md`](docs/report.md) — SDLC discussion, architecture and schema diagrams

## Contact

Al-Rahmeh Association for Animals — admin@alrahmeh.org ·
[Facebook](https://facebook.com/Rahmehforanimals) ·
[Instagram](https://instagram.com/rahmehforanimals)

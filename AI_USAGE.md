# AI Usage Log

One row per meaningful interaction. Routine mechanics — shell syntax errors,
"what's next", reformatting a command — are not logged; only interactions that
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
| 2026-09-25 (planning, no commit) | Claude Code (Opus 5) | Asked for a commit and branching plan against the assignment's cadence requirements: 12+ commits over 6+ calendar days with no day exceeding 40%, every feature on its own branch merged by pull request. | Accepted | No code. Produced the 10-day schedule, the branch-per-feature layout, and the decision to keep each domain branch open across two days so nothing reaches `main` untested. | [Explanation 1](#explanation-1--why-domain-branches-stay-open-across-two-days) |
| 2026-09-25 / `3abfcc2` | Claude Code (Opus 5) | Asked which frontend approach to take given that section 1a permits only one dependency manifest at the repo root, and React requires `package.json` alongside `requirements.txt`. | **Rejected** | The recommendation was Jinja2 templates with vanilla JavaScript, to stay inside the one-manifest rule. I rejected it and secured written approval for React instead. The mitigation I required: `package.json` at the repo root rather than in a subfolder, and the compiled bundle committed to `static/dist`, so Node is build-time only and a clone plus `pip install` plus `python app.py` still serves the whole app. | [Explanation 2](#explanation-2--why-committing-the-built-bundle-is-what-makes-react-work-here) |
| 2026-09-25 / `3abfcc2` | Claude Code (Opus 5) | Asked for the project scaffold under the standing constraints in my brief: environment-driven configuration with no `.env` requirement, dependency injection at the composition root, and the domain packages laid out so neither imports the other. | Accepted | Produced `config.py`, `app.py`, `requirements.txt`, `pytest.ini`, `.coveragerc`, `.gitignore`, `README.md`. Verified before accepting: the server logs `Running on all addresses (0.0.0.0)`, honours `PORT` and `DATA_DIR`, and falls back to port 8000 on a malformed value rather than refusing to boot. | [Explanation 3](#explanation-3--how-the-configuration-layer-works) |
| 2026-09-25 / `3abfcc2` | Claude Code (Opus 5) | Asked for ADR-1 recording the backend framework choice, with the alternatives I had actually weighed. | Accepted | Drafted the Flask-over-Django/FastAPI entry. I accepted the reasoning as written and did not rewrite it. | [Explanation 4](#explanation-4--what-flask-gives-me-over-a-bare-wsgi-application) |

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

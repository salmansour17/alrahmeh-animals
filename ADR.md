# Architecture Decision Record

Decisions are added as they are made, not reconstructed at the end. Each entry
records what forced the decision, what was chosen, what was rejected and why,
and what the choice costs later.

## 1. Flask with stdlib sqlite3 for the backend

Date: 2026-09-25
Status: Decided

Context: The application has two feature domains, roughly five tables, no user
accounts and no long-running or I/O-bound work, and it has to run as a single
process in a single container. I also have to explain every line of it from
memory in a closed-book comprehension check, which penalises any framework
whose behaviour is hidden from me.

Decision: Flask 3.1 for routing and request handling, with the standard
library's `sqlite3` module for persistence and no ORM.

Alternatives considered: **Django** was rejected because almost all of its
value is in the ORM, admin site, auth system and migration framework — I have
no user accounts, five tables, and a deployment contract that forbids a
migration step at startup, so those subsystems would be weight I still had to
defend. **FastAPI** was rejected because its advantages are async request
handling and generated OpenAPI documentation; SQLite calls are synchronous and
local so there is nothing to await, and no external consumer reads a schema, so
adding `uvicorn` and `pydantic` would buy features nothing in this project
uses.

Consequences: Three declared Python dependencies (`flask`, `pytest`,
`pytest-cov`), well under the soft cap, and every SQL statement is visible in
the repository layer rather than generated at runtime — more code to write, but
no query behaviour I cannot account for. Flask returns JSON only; the user
interface is a React bundle that this same process serves as static files, a
split agreed with the course instructor and recorded in the README.

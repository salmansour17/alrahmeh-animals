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

## 2. Each domain is a self-contained package that never imports the other

Date: 2026-09-29
Status: Decided

Context: Animal intake and the donation ledger have to become separate services
in a later assignment, but the deployment contract requires one process now.
The two genuinely touch: a donor can earmark a gift for one animal's treatment,
so the ledger needs to know that an animal id is real.

Decision: `domains/animals/` and `domains/donations/` each own their own
models, repository, service and Flask blueprint, and neither imports anything
from the other; they refer to each other only by primary-key value. When the
ledger needs to check an animal id, it will declare the small interface it
needs in its own package, and `create_app` (the only module that imports both)
will adapt the animal service to it. `tests/test_domain_boundary.py` reads
every source file in both packages and fails if either imports its sibling.

Alternatives considered: A layered layout (one `models.py`, one
`repositories.py`, one `routes.py` for the whole app) was rejected because the
seam would then run through the middle of every file, and splitting the
services later would mean pulling each file apart line by line. Letting the
donations service import `AnimalService` directly was rejected because it is
the one line that would make the ledger impossible to deploy without the
animal code beside it. Splitting into two processes now is ruled out by the
single-container contract (§1c).

Consequences: Splitting the domains later means moving a folder and replacing
one adapter in `create_app` with an HTTP call, and the boundary test proves
that nothing else needs to change. The cost is a little duplication — each
blueprint has its own error handlers — and shared infrastructure
(`db/connection.py`, `security.py`) that each future service would need its own
copy of.

## 3. Cross-domain references are soft; money is stored in minor units

Date: 2026-09-28
Status: Decided

Context: Donors to this organisation frequently give toward one named animal's
treatment, so the ledger has to be able to point at an animal. But the two
domains are meant to be separable into independent services later, and a
foreign key spanning them would have to be dropped and backfilled at that
point. The impact counters on the homepage are a SUM over the ledger, so the
amount column's type also has to survive repeated addition.

Decision: `donations.earmarked_animal_id` stores an `animals.id` value but
declares no FOREIGN KEY, and amounts are stored as `amount_fils INTEGER`, a
count of the Jordanian dinar's minor unit, rather than as a decimal.

Alternatives considered: A real FOREIGN KEY from `donations` to `animals` was
rejected because it would make the storage layer enforce a relationship that
crosses the seam I am trying to preserve — splitting the ledger into its own
service would then require a data migration rather than a code move. Omitting
the column entirely was rejected because earmarked giving is how the
organisation actually raises money for veterinary costs, so losing it would
misrepresent the real use case. Storing amounts as REAL was rejected because
binary floating point cannot represent most decimal amounts exactly and the
error accumulates across a SUM, which is precisely the operation the public
impact figures depend on.

Consequences: SQLite will accept a donation earmarked to an animal id that does
not exist, so that validation now belongs in the donations service where it can
be unit tested. Within domain 1 the opposite choice applies: `medical_records`
and `placement_requests` do declare real foreign keys with ON DELETE CASCADE,
because those relationships never cross a domain boundary and deleting an animal
genuinely should remove its history. Amounts must be converted at the
presentation edge, since 25000 fils has to display as 25.000 JOD.

## 4. Test the rules against real SQLite, exhaustively where the domain is small

Date: 2026-09-30
Status: Decided

Context: Section 4 asks for 70% coverage of the business logic of both domains,
and the parts most likely to be wrong are the ones a coverage figure cannot see:
a transition table with one wrong entry, a money parser that accepts a string it
should not, a total that disagrees with its own breakdown. Each test also has to
be something I can explain, so a large mocking layer counts against it.

Decision: Tests call each domain's service against the real SQLite repository on
a temporary database, and enumerate the whole input space wherever it is small:
all 16 status pairs, each malformed amount string I could think of (including
Arabic-Indic digits and a trailing newline), and both sides of the 10,000 JOD
limit. The only fakes are at the seams the domains declare: a two-line
`FakeAnimalDirectory`, and the `StaleRead` wrapper that simulates a lost race.
Append-only is tested twice: the repository has no mutating method, and a raw
UPDATE or DELETE is refused by SQLite's triggers.

Alternatives considered: Mocking the repository in every service test was
rejected because the mock would only repeat my assumptions about the SQL —
exactly the part most likely to be wrong, such as an empty SUM returning NULL
instead of 0. Counting route handlers towards the 70% was rejected because
Flask glue is easy to cover and says nothing about the rules; `.coveragerc`
leaves `routes.py` out, and a smaller set of HTTP tests checks only access
control, status codes and what the public can see.

Consequences: Business-logic coverage is 100% (provisional, 2026-09-30), but
several things are deliberately thin: the concurrency guarantee is shown with a
simulated stale read, not real threads; there are no frontend tests yet; Stripe
will only ever be exercised through the fake payment adapter, never the real
API; and the ledger has no corrections or reversals to test, because
`CHECK (amount_fils > 0)` rules out a negative compensating row. A mistaken
donation cannot currently be undone, which is a known gap.

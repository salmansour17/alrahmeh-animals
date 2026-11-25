# Architecture Decision Record

Decisions are added as they are made, not reconstructed at the end. Each entry
records what forced the decision, what was chosen, what was rejected and why,
and what the choice costs later.

## 1. Flask with stdlib sqlite3 for the backend

Date: 2026-09-25
Status: Superseded by [7]

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
(Update, 2026-10-04: Stripe and Pillow later brought this to five Python
dependencies, and the enquiries domain and the later features to nine tables;
the reasoning above did not change.)

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
(Update, 2026-10-04: done as described, through `AnimalDirectory` in the
donations service; the enquiries domain added later follows the same rule and
the same test.)

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
Status: Superseded by [7]

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
simulated stale read, not real threads; there are no frontend tests yet; the
real Stripe adapter is tested offline (locally signed webhooks, a replaced
`Session.create`) but never against Stripe's live API in the suite, which is
checked by hand with the Stripe CLI instead; and the ledger has no corrections or reversals to test, because
`CHECK (amount_fils > 0)` rules out a negative compensating row. A mistaken
donation cannot currently be undone, which is a known gap.

## 5. Stripe as a test-mode reference adapter, not the production Jordanian gateway

Date: 2026-10-01
Status: Decided

Context: My professor asked for a Stripe integration to demonstrate SOLID and
design patterns, and I am building from Spain, where a Stripe test account works
immediately. But Stripe does not onboard businesses registered in Jordan, so the
rescue could not take live payments through it, and the test account cannot even
charge in JOD. Regional gateways that can (PayTabs, HyperPay) issue credentials
only through merchant onboarding with the rescue's own business documents, which
is not possible before the deadline.

Decision: I deliberately did not build a production Jordanian gateway. The
donation service depends on a `PaymentGateway` interface it owns (Dependency
Inversion), and `StripeGateway` in `payments.py` is an Adapter that translates
Stripe Checkout and its signed webhooks into the domain's own types, so no
Stripe object reaches the service. Because the test account has no JOD, the
adapter charges US dollars at the Central Bank of Jordan's fixed peg (709 fils
per dollar) and converts the verified amount back into fils. `create_app`
chooses the implementation, so switching provider means one new adapter and one
line there.

Alternatives considered: Building a PayTabs adapter now was rejected: without
sandbox credentials it could not be run, and its payment callback needs a
publicly reachable URL, which section 1a rules out, so it would be untested code
I would have to defend. Calling Stripe directly from the donation service was
rejected because the ledger's rules would then depend on one provider, and
replacing it would mean rewriting business logic and its tests rather than
swapping an adapter. Recording card donations in their charged currency was
rejected because it would break the fils-only ledger that ADR-3 relies on.

Consequences: Card donations work end to end in Stripe test mode only, charged
in USD and recorded in fils, with the original charge kept beside each ledger
row as the audit trail. Going live requires the rescue to open a merchant
account with a regional provider and a new adapter tested against its sandbox,
which would charge JOD directly and need no conversion. Until then, CliQ and
bank-transfer donations are recorded by staff through the existing endpoint.

## 6. Three services along the Assignment 1 seams; donations is the only service that calls another

Date: 2026-11-17
Status: Decided

Context: Assignment 2 asks for one service per feature domain, each in its own
container with its own database, reaching the others only over HTTP. This
project has three domains: animal intake and adoption, the donation and impact
ledger, and enquiries (contact and volunteer messages, added on 2026-10-02 and
kept apart by the same boundary test as the other two). Assignment 2 also
replaces the shared admin password with per-staff accounts, which the staff
endpoints of every service must recognise. Two needs cross between domains. A
donation earmarked for an animal asks, through the one-method `AnimalDirectory`
interface declared in ADR-2, whether that animal exists. And the staff ledger
lists earmarked donations by animal id alone, where staff need the animal's
name: in one database that would have been a join, and after the split the two
tables live in different databases.

Decision: Three services, one per domain, keeping every Assignment 1 boundary.
`animals` owns animals, placements, offline adoptions, photos and the staff
accounts; `donations` owns the ledger, Stripe payments and impact statistics;
`enquiries` owns contact and volunteer messages. Three things cross service
boundaries. The earmark check: `AnimalDirectory` gets a second implementation
that calls `GET /api/animals/<id>` with a timeout, and the donation service
itself does not change. The name lookup: when staff list donations, the
donations service collects the page's distinct animal ids and asks the animals
service for all of their names in one batch call, keeping the answers in memory
for a few minutes because names rarely change; if animals is unreachable, the
list still loads and shows the bare id marked "name unavailable". Both calls go
one way, from donations to animals, and the animals service calls nobody, so it
can be deployed and tested without the others. The staff token: the animals service issues it at
login, and donations and enquiries each check it on their own with a shared
signing key, without calling animals. The homepage counters stay in the
browser, which already calls each service separately. Small infrastructure
files (database connection, migration runner, token check) are copied into each
service, not shared. When the animals service is unreachable or times out,
checkout goes ahead with the earmark marked unverified and the payment webhook
checks it again when the money arrives, so a donor is never turned away; staff
recording an offline donation get a clear 503 asking them to retry, because
they can, and an unchecked typo would otherwise enter an append-only ledger.

Alternatives considered: **Merging enquiries into the animals service** would
give two services, and was rejected because it undoes a domain boundary that
has held since Assignment 1: enquiries share no tables and no rules with
animals, and merging them would leave the boundary test proving less than it
does now. **Every service calling animals to check each staff token** was
rejected because recording a cash donation or reading a message would then
depend on the animals service being up, a runtime dependency bought only to
make revocation instant. **A server-side impact call combining the homepage
counters** was rejected because the browser already does this, and it would
add a cross-service call for data the UI can fetch directly. **One call per
donation row** for the animal's name was rejected because a page of fifty
donations would make up to fifty requests; one batch call per page bounds it.
**Copying animal names into the donations table** when a gift is recorded was
rejected because it would duplicate data the animals service owns, and the
copy would go stale when a name is corrected. **The animals service calling
donations** (for example, to show what was raised for an animal on its profile)
was rejected because calls in both directions would make each service depend on
the other; the browser fetches that figure instead. **A shared Python
package** for the copied infrastructure was rejected because all three services
would then have to release in lockstep, which is the coupling the split exists
to remove.

Consequences: ADR-2 held: the split moves folders and replaces one in-process
adapter with an HTTP client, and the boundary test carries on per service. The
costs: a third container, database, login and Container App, each scaling to
zero (ADR-8 covers what they cost). The name cache can show a name for a few
minutes after it changes, which is harmless in a staff list but means it must
never be used to validate anything; the earmark check always asks fresh.
Integrity across the seam rests on one
HTTP check that checkout deliberately skips during an outage, so a ledger row
can name an animal that does not exist; the webhook logs each unverified
earmark for staff. A deactivated staff account keeps working on donations and
enquiries until its token expires, so the token lifetime is a security
setting, not a convenience. The copied infrastructure exists three times and
must be fixed three times when it changes.

## 7. SQL Server, one database per service, changed only by versioned migrations

Date: 2026-11-18
Status: Decided

Context: Assignment 2 moves storage from one SQLite file to SQL Server, one
database per service (ADR-6), on Azure SQL's serverless tier. Three things in
the Assignment 1 storage stop working there. The schema applied itself with
`CREATE TABLE IF NOT EXISTS` on every boot, which can create a table but never
change one that already holds data. Animal photos were files under DATA_DIR,
and a Container App's filesystem is wiped whenever it scales to zero or is
redeployed. And a serverless database pauses when idle: the first connection
after a quiet hour fails for up to about a minute while it resumes. No
production data existed to carry over, because the Assignment 1 site was never
deployed for the rescue.

Decision: Each service has its own SQL Server database, reached through
`DATABASE_URL` with `pymssql`, and its own login that can use only that
database. Raw SQL stays, as in ADR-1, ported to T-SQL: `BIGINT IDENTITY` ids,
`NVARCHAR` sized to the limits models.py already enforces, `DATE` and
`DATETIME2` columns, and a name on every constraint so a later migration can
refer to it. The decisions of ADR-3 carry over unchanged: money is a whole
number of fils, and `donations.earmarked_animal_id` is a plain id with no
foreign key, which is now the only possible design because the animals table
is in another database. The ledger's append-only rule moves from SQLite
triggers to an `INSTEAD OF UPDATE, DELETE` trigger that throws, so a change
fails loudly instead of doing nothing.

The schema is the numbered files in each service's `migrations/` folder,
applied by our own runner, `migrate.py`. It applies the files the database has
not recorded, in order, each in one transaction together with its row in
`schema_migrations`. It stores each file's SHA-256 and refuses to start if an
applied file has been edited, holds an exclusive application lock
(`sp_getapplock`) so two copies cannot apply the same file at once, and never
drops anything; a test fails if any migration contains DROP, TRUNCATE or
DELETE FROM. It runs as its own start-up step before the web server
(`python migrate.py`), as does adding the sample animals, so neither runs once
per gunicorn worker. Each service starts from `001_init.sql`, the Assignment 1
tables it owns ported to T-SQL. The animals service's `002_animal_photos.sql`
moves photos into a `VARBINARY(MAX)` column, one row per animal with a version
counter that is part of the photo's address. Photos were already re-encoded
and capped at 1600 px, so each row is a few hundred kilobytes.

Connections retry only on the errors that mean "not ready yet": Azure's 40613,
40501 and 40197, and FreeTDS's 20002, 20003 and 20009. They wait 1, 2, 4, 8,
15, 15 and 15 seconds between eight attempts, about a minute in all, which
covers a database resuming from pause. Any other error, such as a wrong
password (18456), fails at once. `?encrypt=true` in the URL makes the driver
require encryption, which Azure SQL insists on.

Alternatives considered: **Alembic** with SQLAlchemy was rejected because it
adds two packages and a model layer to a project that writes its SQL by hand,
and the runner the brief asks for is about a hundred lines I can explain.
**Keeping `CREATE TABLE IF NOT EXISTS`** was rejected because it cannot change
a table that holds data, which is exactly what the next migration has to do.
**pyodbc** was rejected because it needs Microsoft's ODBC driver installed in
the image as a system package, where the `pymssql` wheel brings its own.
**Photos in Blob Storage**, or in a file share mounted into the container, were
rejected because each is another Azure resource with its own credentials, and
the brief allows one storage account, which serves the website. **One shared
database with a schema per service** was rejected because the brief requires a
database per service, and a shared one would let a service read another's
tables.

Recovery from a bad migration: migrations are forward-only. A migration that
fails rolls back entirely, nothing is recorded, the service does not start,
and the pipeline's health check fails the deployment; the fix is a corrected
migration in a new file and a new deploy. A migration that applies but is
wrong is corrected the same way, by a new migration, never by editing the
applied one (the checksum stops that). If data itself is damaged, Azure SQL's
automatic backups allow a point-in-time restore into a new database, which the
service is then pointed at through `DATABASE_URL`.

Consequences: Integrity lost at the seam: nothing in the database stops a
donation from naming an animal that does not exist. It is compensated in code:
the donations service checks the id over HTTP on every write (ADR-6), checkout
and the payment webhook record an unverified earmark only while the animals
service is unreachable and log each one for staff, and no endpoint in any
service deletes an animal, so an id that was checked stays valid. The tests
now need a SQL Server and take about a minute for the animals service instead
of ten seconds; each run creates its own throwaway database and drops it at
the end. Photos count toward the free offer's 32 GB per database, which at a
few hundred kilobytes each is tens of thousands of photos. Startup includes a
migration check and, after an idle hour, possibly a minute of waiting for the
database, which the website has to present as "starting up" rather than as an
error (ADR-8).

## 8. Serverless hosting on Azure, each concern its own piece of Terraform

Date: 2026-11-19
Status: Decided

Context: The brief requires Azure Container Apps on the Consumption plan, Azure
SQL Database serverless, a Storage static website and nothing that runs or
costs money while the site is idle. My professor asked to see each deployment
concern built as its own visible piece, not left to a tool that does
everything. The pipeline signs in as a managed identity that is Contributor on
one resource group only, so it cannot create that resource group, register
resource providers, or grant roles. And everything scales to zero, so the first
visit after a quiet hour finds a stopped container and possibly a paused
database.

Decision: Terraform in `infra/` defines the Container Apps environment, the
three Container Apps and the SQL server with its firewall rule; a one-time,
documented bootstrap (`docs/deployment.md`) creates the resource group, the
storage account (website plus Terraform's state) and the pipeline's identity,
which Terraform only reads. Each concern is a block I can point to:

- Scaling and load: each app has `min_replicas = 0`, `max_replicas = 1` and an
  explicit HTTP scale rule (`concurrent_requests = "10"`). Requests reach the
  app through Container Apps' ingress, which also wakes it from zero.
- Network and firewall: ingress is external and HTTPS-only
  (`allow_insecure_connections = false`) because the browser calls every
  service; CORS is enforced in each service's code for the website's origin
  only, read from the storage account; the SQL server accepts only Azure
  services (the 0.0.0.0 rule) and TLS 1.2 or newer, and each service connects
  as a user that exists only in its own database.
- Health: a startup probe on `/health` allows up to five minutes (30 checks,
  10 s apart) for migrations and a paused database; a readiness probe keeps
  traffic away from a replica whose database is unreachable. There is no
  liveness probe on `/health`, because a paused database is not a reason to
  restart a container.
- Secrets: the connection strings, the staff password and the optional Stripe
  keys are Container Apps `secret` blocks referenced by `secret_name`, fed from
  GitHub secrets as sensitive Terraform variables; none is a plain
  environment variable or in the repository.
- Caching: built website assets are uploaded with a one-year immutable
  `Cache-Control`, `index.html` and `config.js` with `no-cache`.

The azurerm provider has no argument for Azure SQL's free offer, so the
pipeline creates each database with `az sql db create --use-free-limit true
--free-limit-exhaustion-behavior AutoPause` (General Purpose serverless Gen5,
0.5 to 1 vCore, locally redundant backups) when it does not exist yet, and
never touches one that does. Images go to GitHub Container Registry, tagged
with the commit SHA.

Alternatives considered: **Azure CLI commands for everything**, as the setup
guide shows, would work, but each run would have to work out what already
exists, and the configuration would be scattered through a script rather than
declared in one place I can read. **The azapi provider** could set the free
offer through Azure's REST API and keep the databases in Terraform; it was
rejected for now as a second provider whose resource bodies are raw API JSON,
for one setting. **Azure Container Registry** has a fixed monthly cost, which
the brief rules out unless justified; GHCR is free. **A Log Analytics
workspace** would keep the logs searchable but is another resource billed per
GB; without it, the container logs are still streamed. **min_replicas = 1**
would remove cold starts but run three containers all month.

Consequences: Cost follows use. A Container App is billed while a replica
runs and nothing while it is scaled to zero; the databases are on the free
offer and pause after 60 minutes idle, and if the free allowance runs out they
pause rather than bill; the website is storage and requests. The exact monthly
figures are to confirm after a week of real use. The price is the cold start:
after an idle hour, the first visitor waits while a container starts and its
database resumes, which can take about a minute. `db.py` retries the
connection with backoff for about a minute, the startup probe allows five, the
pipeline's health check waits five, and the website must show "starting up"
rather than an error (planned for Nov 21). A two-second deadline on the
earmark check (ADR-6) may often expire while the animals service is waking;
how often is to confirm on Azure. `max_replicas = 1` also means migrations at
start-up never run twice at once, with `sp_getapplock` as a second guard. The
real addresses, whether the free offer applied, and cold-start timings are to
confirm on the first deploy.

At a hundred times the traffic: raise `max_replicas` and the scale rule's
threshold, and run migrations as a separate step before the new revision
rolls out instead of at start-up; keep `min_replicas = 1` on the animals
service so the earmark check stops meeting cold starts; move the databases off
the free offer to a larger serverless or provisioned size, and pool
connections instead of opening one per request; and put a CDN in front of the
static website.

**Amended 2026-11-25, at the first deploy.** Two assumptions above did not
hold. Azure would not create a SQL server in `germanywestcentral` for this
subscription, so the server is in `spaincentral` (`SQL_LOCATION`), while the
Container Apps stay in `germanywestcentral`; each database call therefore
crosses two regions, which adds a few tens of milliseconds. And Azure refused
the free offer in every region the subscription may use, so, with my
professor's agreement, the databases are ordinary serverless ones: General
Purpose Gen5, 0.5 to 1 vCore, paused after 15 idle minutes (the shortest
allowed, down from the free offer's fixed 60), at most 1 GB each, locally
redundant backups. Cost now follows use in the databases too: paused, the
three cost about $0.41 a month in storage; awake, about $0.29 an hour each,
and every wake bills at least the 15 minutes before it can pause again.
Nothing may wake them on a timer: kept awake around the clock, the three would
use the $100 student credit in about five days. The 1 GB ceiling holds the
current data, photos included, many times over, and raising it is one
in-place command. The reason for creating the databases with `az` instead of
Terraform was the free offer, which no longer applies; they stay with `az`
for now because they already exist, and moving them into Terraform would mean
importing them.

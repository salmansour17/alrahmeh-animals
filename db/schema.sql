-- Schema for the Al-Rahmeh Association for Animals application.
--
-- This file is applied on every startup. Every statement is idempotent, which
-- is what allows the deployment contract's "no interactive setup, no manual
-- migration" requirement to be met: a fresh container and an existing one run
-- exactly the same code path.
--
-- PRAGMA foreign_keys is deliberately NOT set here. It is a per-connection
-- setting in SQLite, so it is applied in db/connection.py instead; setting it
-- in this file would silently apply to the initialising connection only.


-- ===========================================================================
-- Domain 1: animal intake and adoption
-- ===========================================================================

-- The animal record itself. `status` is the placement lifecycle; the CHECK
-- constraint is a backstop only, because the legal transitions between these
-- values are enforced in domains/animals/service.py where they can be tested.
CREATE TABLE IF NOT EXISTS animals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    species        TEXT    NOT NULL,
    breed          TEXT,
    date_of_intake TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'available'
                           CHECK (status IN ('available', 'fostering', 'pending', 'adopted')),
    notes          TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_animals_status ON animals (status);

-- Vaccination and treatment history. One animal has many records; deleting an
-- animal removes its history, which is why this cascades.
CREATE TABLE IF NOT EXISTS medical_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    animal_id   INTEGER NOT NULL REFERENCES animals (id) ON DELETE CASCADE,
    record_type TEXT    NOT NULL CHECK (record_type IN ('vaccination', 'treatment', 'checkup')),
    description TEXT    NOT NULL,
    occurred_on TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_medical_records_animal ON medical_records (animal_id);

-- Adoption and foster applications. This is what replaces the Google Forms the
-- live site currently sends "Adopt Now" and "Foster Now" to: a request is a
-- record attached to a real animal, and acting on it drives that animal's
-- status transition.
CREATE TABLE IF NOT EXISTS placement_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    animal_id       INTEGER NOT NULL REFERENCES animals (id) ON DELETE CASCADE,
    kind            TEXT    NOT NULL CHECK (kind IN ('adoption', 'foster')),
    applicant_name  TEXT    NOT NULL,
    applicant_email TEXT    NOT NULL,
    message         TEXT,
    outcome         TEXT    NOT NULL DEFAULT 'open'
                            CHECK (outcome IN ('open', 'approved', 'declined')),
    submitted_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_placement_requests_animal ON placement_requests (animal_id);

-- Placement history. animals.status holds only where an animal is now; this
-- records every move and when it happened, so staff can see that an animal
-- went back from a foster before being adopted. A row is written in the same
-- transaction as the status UPDATE it describes, so the two cannot disagree.
-- Being a new table rather than a new column, it creates itself on an existing
-- database too: CREATE TABLE IF NOT EXISTS never alters a table already there.
CREATE TABLE IF NOT EXISTS status_changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    animal_id   INTEGER NOT NULL REFERENCES animals (id) ON DELETE CASCADE,
    from_status TEXT    NOT NULL
                        CHECK (from_status IN ('available', 'fostering', 'pending', 'adopted')),
    to_status   TEXT    NOT NULL
                        CHECK (to_status IN ('available', 'fostering', 'pending', 'adopted')),
    reason      TEXT,
    changed_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_status_changes_animal ON status_changes (animal_id);


-- Adoptions arranged entirely in person: for animals never entered here, or
-- from before the site existed. Staff record them as dated entries with a
-- count; the homepage's "found homes" figure adds them to the adopted animals
-- on record, so every part of that number is something staff entered.
CREATE TABLE IF NOT EXISTS offline_adoptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    animal_count INTEGER NOT NULL CHECK (animal_count > 0),
    adopted_on  TEXT    NOT NULL,
    note        TEXT,
    recorded_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ===========================================================================
-- Domain 2: donation and impact ledger
-- ===========================================================================

-- Append-only ledger. Nothing in the application updates or deletes a row
-- here, which is what makes the homepage impact figures reproducible from the
-- table alone, and the two triggers below make SQLite itself refuse to. Mistakes
-- are not yet correctable: CHECK (amount_fils > 0) rules out a negative
-- compensating row, so a correction mechanism is a known gap (ADR-4).
--
-- received_at holds an ISO date (2026-09-30) that the application always
-- supplies: staff record cash days after it arrives, so the date is chosen,
-- not stamped. The datetime('now') default is a backstop that is never used.
--
-- Money is stored as an INTEGER count of fils, the minor unit of the Jordanian
-- dinar (1 JOD = 1000 fils). Storing currency as a REAL would accumulate
-- binary rounding error across a SUM, and the impact counters are a SUM.
--
-- earmarked_animal_id is a soft reference: it holds an animals.id value but
-- declares no FOREIGN KEY. See ADR-3 — a real constraint here would weld the
-- two domains together at the storage layer and make separating them into two
-- services impossible without a data migration.
CREATE TABLE IF NOT EXISTS donations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_name          TEXT,
    amount_fils         INTEGER NOT NULL CHECK (amount_fils > 0),
    currency            TEXT    NOT NULL DEFAULT 'JOD',
    purpose             TEXT    NOT NULL
                                CHECK (purpose IN ('medical_fund', 'food_fund', 'general')),
    earmarked_animal_id INTEGER,
    received_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_donations_purpose ON donations (purpose);
CREATE INDEX IF NOT EXISTS idx_donations_received_at ON donations (received_at);

-- Append-only, enforced by the database rather than promised by the code. Like
-- the tables, these create themselves on an existing database at boot.
CREATE TRIGGER IF NOT EXISTS donations_no_update BEFORE UPDATE ON donations
BEGIN
    SELECT RAISE(ABORT, 'donations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS donations_no_delete BEFORE DELETE ON donations
BEGIN
    SELECT RAISE(ABORT, 'donations are append-only');
END;

-- Card payments confirmed by the payment provider. One row per paid Checkout
-- session, written in the same transaction as the donation it produced. The
-- UNIQUE session_id is what makes a replayed webhook harmless: the second
-- insert conflicts, the transaction rolls back, and no second donation exists.
-- A separate table rather than a column on donations, because
-- CREATE TABLE IF NOT EXISTS reaches existing databases and ALTER would need a
-- migration step. The foreign key stays inside the donations domain.
--
-- charged_amount_minor and charged_currency are what Stripe actually charged
-- (US cents in test mode, because the test account cannot hold JOD). The
-- donation row holds the same money converted to fils at the Central Bank of
-- Jordan's fixed peg; keeping both side by side is the audit trail for that
-- conversion.
CREATE TABLE IF NOT EXISTS stripe_payments (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT    NOT NULL UNIQUE,
    donation_id          INTEGER NOT NULL UNIQUE REFERENCES donations (id),
    charged_amount_minor INTEGER NOT NULL CHECK (charged_amount_minor > 0),
    charged_currency     TEXT    NOT NULL,
    recorded_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);


-- ===========================================================================
-- Domain 3: enquiries (contact and volunteer messages)
-- ===========================================================================

-- What the public sends through the contact form. Personal data: staff-only,
-- never logged. Staff mark each one handled once they have replied.
CREATE TABLE IF NOT EXISTS enquiries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT    NOT NULL
                        CHECK (topic IN ('volunteer', 'question', 'shop_order', 'other')),
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL,
    subject     TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    handled     INTEGER NOT NULL DEFAULT 0 CHECK (handled IN (0, 1)),
    received_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_enquiries_handled ON enquiries (handled);

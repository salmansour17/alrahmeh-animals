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


-- ===========================================================================
-- Domain 2: donation and impact ledger
-- ===========================================================================

-- Append-only ledger. Nothing in the application updates or deletes a row
-- here: a correction is a new compensating row, which is what makes the
-- homepage impact figures reproducible from the table alone.
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

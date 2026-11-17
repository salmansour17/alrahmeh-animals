-- Schema for the animals service of the Al-Rahmeh Association for Animals.
--
-- Temporary: this file is the Assignment 1 schema, cut down to the tables this
-- service owns. It is replaced by numbered migrations in the SQL Server port.
--
-- This file is applied on every startup. Every statement is idempotent, which
-- is what allows the deployment contract's "no interactive setup, no manual
-- migration" requirement to be met: a fresh container and an existing one run
-- exactly the same code path.
--
-- PRAGMA foreign_keys is deliberately NOT set here. It is a per-connection
-- setting in SQLite, so it is applied in db.py instead; setting it
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


-- The public "about me" details of an animal: one optional row per animal.
-- A separate table rather than new columns on animals, because
-- CREATE TABLE IF NOT EXISTS reaches existing databases and ALTER TABLE would
-- need a migration step. Age is stored as a date of birth so it is never out
-- of date; weight as whole grams so no decimal ever reaches the database.
CREATE TABLE IF NOT EXISTS animal_profiles (
    animal_id    INTEGER PRIMARY KEY REFERENCES animals (id) ON DELETE CASCADE,
    born_on      TEXT,
    colour       TEXT,
    personality  TEXT,
    weight_grams INTEGER CHECK (weight_grams IS NULL OR weight_grams > 0),
    about        TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

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


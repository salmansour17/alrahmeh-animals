-- Schema for the enquiries service of the Al-Rahmeh Association for Animals.
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

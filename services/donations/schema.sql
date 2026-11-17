-- Schema for the donations service of the Al-Rahmeh Association for Animals.
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



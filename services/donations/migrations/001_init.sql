-- 001: the donations service's tables, ported from the Assignment 1 SQLite
-- schema to SQL Server.
--
-- Applied once by migrate.py and recorded in schema_migrations. Never edit this
-- file after it has been applied anywhere: put changes in a new migration.
-- Every constraint has a name, so a later migration can refer to it.


-- The append-only ledger. Nothing in the application updates or deletes a row
-- here, which is what makes the homepage impact figures reproducible from the
-- table alone, and the trigger below makes the database itself refuse to.
--
-- Money is a BIGINT count of fils, the minor unit of the Jordanian dinar
-- (1 JOD = 1000 fils). A floating-point type would accumulate rounding error
-- across a SUM, and the impact counters are a SUM.
--
-- received_at holds the date staff say the money arrived (cash is often
-- recorded days later), so it is a DATE the application always supplies.
--
-- earmarked_animal_id holds an id from the animals service, which has its own
-- database. There is no foreign key and there cannot be one: the check that the
-- animal exists is an HTTP call made by donations/service.py (ADR-3, ADR-6).
CREATE TABLE donations (
    id                  BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_donations PRIMARY KEY,
    donor_name          NVARCHAR(120) NULL,
    amount_fils         BIGINT        NOT NULL CONSTRAINT ck_donations_amount CHECK (amount_fils > 0),
    currency            NCHAR(3)      NOT NULL CONSTRAINT df_donations_currency DEFAULT N'JOD',
    purpose             NVARCHAR(20)  NOT NULL
                                      CONSTRAINT ck_donations_purpose
                                      CHECK (purpose IN (N'medical_fund', N'food_fund', N'general')),
    earmarked_animal_id BIGINT        NULL,
    received_at         DATE          NOT NULL,
    created_at          DATETIME2(0)  NOT NULL CONSTRAINT df_donations_created_at DEFAULT SYSUTCDATETIME()
);

CREATE INDEX ix_donations_purpose ON donations (purpose);
CREATE INDEX ix_donations_received_at ON donations (received_at);

-- Card payments confirmed by the payment provider: one row per paid Checkout
-- session, written in the same transaction as the donation it produced. The
-- UNIQUE session_id is what makes a replayed webhook harmless: the second
-- insert fails, the transaction rolls back, and no second donation exists.
--
-- charged_amount_minor and charged_currency are what Stripe actually charged
-- (US cents in test mode, because the test account cannot hold JOD). The
-- donation row holds the same money converted to fils (ADR-5); keeping both
-- side by side is the audit trail for that conversion.
CREATE TABLE stripe_payments (
    id                   BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_stripe_payments PRIMARY KEY,
    session_id           NVARCHAR(255) NOT NULL CONSTRAINT uq_stripe_payments_session UNIQUE,
    donation_id          BIGINT        NOT NULL
                                       CONSTRAINT uq_stripe_payments_donation UNIQUE
                                       CONSTRAINT fk_stripe_payments_donation REFERENCES donations (id),
    charged_amount_minor BIGINT        NOT NULL CONSTRAINT ck_stripe_payments_amount CHECK (charged_amount_minor > 0),
    charged_currency     NVARCHAR(10)  NOT NULL,
    recorded_at          DATETIME2(0)  NOT NULL CONSTRAINT df_stripe_payments_recorded_at DEFAULT SYSUTCDATETIME()
);
GO

-- Append-only, enforced by the database rather than promised by the code. An
-- INSTEAD OF trigger runs in place of the UPDATE or DELETE, and THROW makes the
-- statement fail loudly and rolls its transaction back. CREATE TRIGGER must be
-- the first statement in its batch, hence the GO above.
CREATE TRIGGER tr_donations_append_only ON donations
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    THROW 51000, 'donations are append-only', 1;
END;

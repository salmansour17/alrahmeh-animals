-- 003: corrections to the ledger, recorded as reversals.
--
-- The ledger stays append-only: the trigger from 001 still refuses every
-- UPDATE and DELETE, and nothing here touches it. A donation recorded by
-- mistake is corrected by a NEW row, a reversal, that cancels it: the
-- compensating action of a saga, never an edit. The impact figures subtract
-- reversed money (repository.py).
--
-- This changes a table that already holds data, in place, as §4.6 asks:
--   - kind: 'gift' or 'reversal'. NOT NULL with a DEFAULT, so every row
--     already there becomes 'gift' as the column is added. There is no UPDATE
--     anywhere in this file: the trigger would refuse one, and it stays on.
--   - reverses_donation_id: the gift a reversal cancels; NULL on a gift.
--   - reversal_reason: why staff reversed it; NULL on a gift. There was no
--     notes column to reuse, so this is a third column.
--   - reverses_kind: computed, PERSISTED, 'gift' whenever
--     reverses_donation_id is set. It only exists so the foreign key below
--     can say "the target must be a gift".
--
-- Rules, all enforced by the database, not only by the code:
--   - a row is either a gift (no target, no reason) or a reversal (both);
--   - a reversal points at a real donation of kind 'gift', so it can never
--     point at another reversal: the foreign key is on (id, kind) and the
--     reversal's side of it is always 'gift';
--   - a gift can be reversed once: a filtered unique index, because a UNIQUE
--     constraint in SQL Server would allow only one NULL, i.e. one gift.
--
-- Batches are split by GO: a batch cannot use a column added earlier in the
-- same batch, so the columns come first and everything that uses them after.
-- The runner applies all of the batches in one transaction: all or nothing.


ALTER TABLE donations ADD
    kind                 NVARCHAR(10)  NOT NULL CONSTRAINT df_donations_kind DEFAULT N'gift',
    reverses_donation_id BIGINT        NULL,
    reversal_reason      NVARCHAR(500) NULL;
GO

ALTER TABLE donations ADD
    reverses_kind AS (CAST(CASE WHEN reverses_donation_id IS NULL THEN NULL ELSE N'gift' END AS NVARCHAR(10))) PERSISTED;
GO

ALTER TABLE donations ADD
    CONSTRAINT ck_donations_kind CHECK (kind IN (N'gift', N'reversal')),
    CONSTRAINT ck_donations_reversal_shape CHECK (
        (kind = N'gift' AND reverses_donation_id IS NULL AND reversal_reason IS NULL)
        OR (kind = N'reversal' AND reverses_donation_id IS NOT NULL AND reversal_reason IS NOT NULL)
    ),
    -- The key the foreign key below refers to. id alone is already unique;
    -- (id, kind) is what lets a reference require a particular kind.
    CONSTRAINT uq_donations_id_kind UNIQUE (id, kind);
GO

ALTER TABLE donations ADD
    CONSTRAINT fk_donations_reverses_gift FOREIGN KEY (reverses_donation_id, reverses_kind)
        REFERENCES donations (id, kind);
GO

CREATE UNIQUE INDEX ux_donations_reversed_once
    ON donations (reverses_donation_id)
    WHERE reverses_donation_id IS NOT NULL;

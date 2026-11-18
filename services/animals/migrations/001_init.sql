-- 001: the animals service's tables, ported from the Assignment 1 SQLite schema
-- to SQL Server.
--
-- Applied once by migrate.py and recorded in schema_migrations. Never edit this
-- file after it has been applied anywhere: put changes in a new migration.
--
-- Translation from SQLite:
--   INTEGER PRIMARY KEY AUTOINCREMENT  ->  BIGINT IDENTITY(1,1)
--   TEXT                               ->  NVARCHAR(n), n at least the limit
--                                          models.py enforces
--   TEXT holding an ISO date           ->  DATE
--   DEFAULT (datetime('now'))          ->  DATETIME2(0) DEFAULT SYSUTCDATETIME()
-- Every constraint has a name, so a later migration can refer to it.


-- The animal record itself. `status` is the placement lifecycle; the CHECK is a
-- backstop only, because the legal transitions between these values are
-- enforced in animals/service.py where they can be tested.
CREATE TABLE animals (
    id             BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_animals PRIMARY KEY,
    name           NVARCHAR(80)   NOT NULL,
    species        NVARCHAR(40)   NOT NULL,
    breed          NVARCHAR(80)   NULL,
    date_of_intake DATE           NOT NULL,
    status         NVARCHAR(10)   NOT NULL CONSTRAINT df_animals_status DEFAULT N'available'
                                  CONSTRAINT ck_animals_status
                                  CHECK (status IN (N'available', N'fostering', N'pending', N'adopted')),
    notes          NVARCHAR(2000) NULL,
    created_at     DATETIME2(0)   NOT NULL CONSTRAINT df_animals_created_at DEFAULT SYSUTCDATETIME()
);

CREATE INDEX ix_animals_status ON animals (status);

-- Vaccination and treatment history. Deleting an animal removes its history,
-- which is why this cascades.
CREATE TABLE medical_records (
    id          BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_medical_records PRIMARY KEY,
    animal_id   BIGINT        NOT NULL
                              CONSTRAINT fk_medical_records_animal REFERENCES animals (id) ON DELETE CASCADE,
    record_type NVARCHAR(20)  NOT NULL
                              CONSTRAINT ck_medical_records_type
                              CHECK (record_type IN (N'vaccination', N'treatment', N'checkup')),
    description NVARCHAR(500) NOT NULL,
    occurred_on DATE          NOT NULL,
    created_at  DATETIME2(0)  NOT NULL CONSTRAINT df_medical_records_created_at DEFAULT SYSUTCDATETIME()
);

CREATE INDEX ix_medical_records_animal ON medical_records (animal_id);

-- Adoption and foster applications: what replaces the old site's Google Forms.
-- A request is attached to a real animal, and a staff decision on it is what
-- moves that animal.
CREATE TABLE placement_requests (
    id              BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_placement_requests PRIMARY KEY,
    animal_id       BIGINT         NOT NULL
                                   CONSTRAINT fk_placement_requests_animal REFERENCES animals (id) ON DELETE CASCADE,
    kind            NVARCHAR(10)   NOT NULL
                                   CONSTRAINT ck_placement_requests_kind CHECK (kind IN (N'adoption', N'foster')),
    applicant_name  NVARCHAR(120)  NOT NULL,
    applicant_email NVARCHAR(254)  NOT NULL,
    message         NVARCHAR(2000) NULL,
    outcome         NVARCHAR(10)   NOT NULL CONSTRAINT df_placement_requests_outcome DEFAULT N'open'
                                   CONSTRAINT ck_placement_requests_outcome
                                   CHECK (outcome IN (N'open', N'approved', N'declined')),
    submitted_at    DATETIME2(0)   NOT NULL CONSTRAINT df_placement_requests_submitted_at DEFAULT SYSUTCDATETIME()
);

CREATE INDEX ix_placement_requests_animal ON placement_requests (animal_id);

-- Placement history: every status move and when it happened. A row is written
-- in the same transaction as the status UPDATE it describes.
CREATE TABLE status_changes (
    id          BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_status_changes PRIMARY KEY,
    animal_id   BIGINT        NOT NULL
                              CONSTRAINT fk_status_changes_animal REFERENCES animals (id) ON DELETE CASCADE,
    from_status NVARCHAR(10)  NOT NULL
                              CONSTRAINT ck_status_changes_from
                              CHECK (from_status IN (N'available', N'fostering', N'pending', N'adopted')),
    to_status   NVARCHAR(10)  NOT NULL
                              CONSTRAINT ck_status_changes_to
                              CHECK (to_status IN (N'available', N'fostering', N'pending', N'adopted')),
    reason      NVARCHAR(500) NULL,
    changed_at  DATETIME2(0)  NOT NULL CONSTRAINT df_status_changes_changed_at DEFAULT SYSUTCDATETIME()
);

CREATE INDEX ix_status_changes_animal ON status_changes (animal_id);

-- The public "about me" details: at most one row per animal. Age is stored as
-- a date of birth so it is never out of date; weight as whole grams so no
-- decimal reaches the database.
CREATE TABLE animal_profiles (
    animal_id    BIGINT         NOT NULL CONSTRAINT pk_animal_profiles PRIMARY KEY
                                CONSTRAINT fk_animal_profiles_animal REFERENCES animals (id) ON DELETE CASCADE,
    born_on      DATE           NULL,
    colour       NVARCHAR(40)   NULL,
    personality  NVARCHAR(60)   NULL,
    weight_grams INT            NULL CONSTRAINT ck_animal_profiles_weight
                                CHECK (weight_grams IS NULL OR weight_grams > 0),
    about        NVARCHAR(1000) NULL,
    updated_at   DATETIME2(0)   NOT NULL CONSTRAINT df_animal_profiles_updated_at DEFAULT SYSUTCDATETIME()
);

-- Adoptions arranged entirely in person, recorded by staff as dated entries
-- with a count. The homepage's "found homes" figure adds them to the adopted
-- animals on record.
CREATE TABLE offline_adoptions (
    id           BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_offline_adoptions PRIMARY KEY,
    animal_count INT           NOT NULL CONSTRAINT ck_offline_adoptions_count CHECK (animal_count > 0),
    adopted_on   DATE          NOT NULL,
    note         NVARCHAR(500) NULL,
    recorded_at  DATETIME2(0)  NOT NULL CONSTRAINT df_offline_adoptions_recorded_at DEFAULT SYSUTCDATETIME()
);

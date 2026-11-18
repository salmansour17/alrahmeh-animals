-- 002: animal photos move from files on disk into the database.
--
-- In Assignment 1 each photo was a file under DATA_DIR/photos. A Container App's
-- filesystem is wiped whenever it scales to zero or is redeployed, so a photo
-- saved there would vanish; the database is the one place this service keeps
-- that survives (ADR-7). Photos are re-encoded and capped at 1600 px before they
-- are stored (animals/photos.py), so each is a few hundred kilobytes.
--
-- One row per animal that has a photo. `version` goes up by one on every
-- replacement: it is part of the photo's address (?v=3), so a browser that
-- cached the old picture fetches the new one.
--
-- A new table, so no existing row is touched.

CREATE TABLE animal_photos (
    animal_id  BIGINT          NOT NULL CONSTRAINT pk_animal_photos PRIMARY KEY
                               CONSTRAINT fk_animal_photos_animal REFERENCES animals (id) ON DELETE CASCADE,
    photo      VARBINARY(MAX)  NOT NULL,
    version    INT             NOT NULL CONSTRAINT df_animal_photos_version DEFAULT 1
                               CONSTRAINT ck_animal_photos_version CHECK (version > 0),
    updated_at DATETIME2(0)    NOT NULL CONSTRAINT df_animal_photos_updated_at DEFAULT SYSUTCDATETIME()
);

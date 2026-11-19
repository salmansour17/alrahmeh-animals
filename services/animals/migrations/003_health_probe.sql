-- 003: a one-row table that GET /health writes to and reads back.
--
-- The brief asks /health to answer 200 only when the service can read AND write
-- its own database. Writing to a real table would mean inventing test rows in
-- domain data, so the check moves the timestamp on this table's single row
-- instead (db.py, check_read_write). The CHECK keeps it to one row, so the
-- table never grows however often the platform probes.
--
-- A new table, so no existing row is touched.

CREATE TABLE health_probe (
    id         TINYINT      NOT NULL CONSTRAINT pk_health_probe PRIMARY KEY
                            CONSTRAINT ck_health_probe_single_row CHECK (id = 1),
    checked_at DATETIME2(0) NOT NULL CONSTRAINT df_health_probe_checked_at DEFAULT SYSUTCDATETIME()
);

INSERT INTO health_probe (id) VALUES (1);

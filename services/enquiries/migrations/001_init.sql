-- 001: the enquiries service's table, ported from the Assignment 1 SQLite
-- schema to SQL Server.
--
-- Applied once by migrate.py and recorded in schema_migrations. Never edit this
-- file after it has been applied anywhere: put changes in a new migration.
-- Every constraint has a name, so a later migration can refer to it.


-- What the public sends through the contact and volunteer form. Personal data:
-- staff-only, never logged. Staff mark each one handled once they have replied.
CREATE TABLE enquiries (
    id          BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_enquiries PRIMARY KEY,
    topic       NVARCHAR(20)   NOT NULL
                               CONSTRAINT ck_enquiries_topic
                               CHECK (topic IN (N'volunteer', N'question', N'shop_order', N'other')),
    name        NVARCHAR(120)  NOT NULL,
    email       NVARCHAR(254)  NOT NULL,
    subject     NVARCHAR(150)  NOT NULL,
    message     NVARCHAR(4000) NOT NULL,
    handled     BIT            NOT NULL CONSTRAINT df_enquiries_handled DEFAULT 0,
    received_at DATETIME2(0)   NOT NULL CONSTRAINT df_enquiries_received_at DEFAULT SYSUTCDATETIME()
);

CREATE INDEX ix_enquiries_handled ON enquiries (handled);

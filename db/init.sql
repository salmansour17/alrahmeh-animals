-- Local setup of the SQL Server that docker-compose.yml starts: one database
-- per service, and one login per service that can use only its own database.
--
-- Run by the one-off `db-init` service in docker-compose.yml with sqlcmd,
-- which fills in $(ANIMALS_PASSWORD), $(DONATIONS_PASSWORD) and
-- $(ENQUIRIES_PASSWORD) from the shell's environment. No password is written
-- in this file.
--
-- Safe to run twice, and it runs on every `docker compose up`: each object is
-- created only if it is missing, and nothing is dropped. A login that already
-- exists has its password set again, so changing a password in the shell and
-- restarting is enough to change it here.
--
-- The tables are not created here. Each service creates and changes its own
-- with its migrations when it starts (migrate.py). On Azure the same three
-- databases and users are created once during the initial setup instead.

SET NOCOUNT ON;

IF DB_ID(N'animals') IS NULL CREATE DATABASE animals;
IF DB_ID(N'donations') IS NULL CREATE DATABASE donations;
IF DB_ID(N'enquiries') IS NULL CREATE DATABASE enquiries;
GO

-- Logins live in the server; a login reaches a database only through a user
-- created inside that database. Each login below gets a user in its own
-- database and nowhere else, so animals_app cannot open the donations
-- database, and so on.
IF SUSER_ID(N'animals_app') IS NULL
    CREATE LOGIN animals_app WITH PASSWORD = N'$(ANIMALS_PASSWORD)', DEFAULT_DATABASE = animals;
ELSE
    ALTER LOGIN animals_app WITH PASSWORD = N'$(ANIMALS_PASSWORD)';

IF SUSER_ID(N'donations_app') IS NULL
    CREATE LOGIN donations_app WITH PASSWORD = N'$(DONATIONS_PASSWORD)', DEFAULT_DATABASE = donations;
ELSE
    ALTER LOGIN donations_app WITH PASSWORD = N'$(DONATIONS_PASSWORD)';

IF SUSER_ID(N'enquiries_app') IS NULL
    CREATE LOGIN enquiries_app WITH PASSWORD = N'$(ENQUIRIES_PASSWORD)', DEFAULT_DATABASE = enquiries;
ELSE
    ALTER LOGIN enquiries_app WITH PASSWORD = N'$(ENQUIRIES_PASSWORD)';
GO

-- Inside each database: the service's user, with exactly what it needs.
-- db_ddladmin lets its migrations create and change tables; db_datareader and
-- db_datawriter let it read and write rows. It cannot manage logins, other
-- users or the database itself.
USE animals;
IF USER_ID(N'animals_app') IS NULL CREATE USER animals_app FOR LOGIN animals_app;
IF IS_ROLEMEMBER(N'db_ddladmin', N'animals_app') = 0 ALTER ROLE db_ddladmin ADD MEMBER animals_app;
IF IS_ROLEMEMBER(N'db_datareader', N'animals_app') = 0 ALTER ROLE db_datareader ADD MEMBER animals_app;
IF IS_ROLEMEMBER(N'db_datawriter', N'animals_app') = 0 ALTER ROLE db_datawriter ADD MEMBER animals_app;
GO

USE donations;
IF USER_ID(N'donations_app') IS NULL CREATE USER donations_app FOR LOGIN donations_app;
IF IS_ROLEMEMBER(N'db_ddladmin', N'donations_app') = 0 ALTER ROLE db_ddladmin ADD MEMBER donations_app;
IF IS_ROLEMEMBER(N'db_datareader', N'donations_app') = 0 ALTER ROLE db_datareader ADD MEMBER donations_app;
IF IS_ROLEMEMBER(N'db_datawriter', N'donations_app') = 0 ALTER ROLE db_datawriter ADD MEMBER donations_app;
GO

USE enquiries;
IF USER_ID(N'enquiries_app') IS NULL CREATE USER enquiries_app FOR LOGIN enquiries_app;
IF IS_ROLEMEMBER(N'db_ddladmin', N'enquiries_app') = 0 ALTER ROLE db_ddladmin ADD MEMBER enquiries_app;
IF IS_ROLEMEMBER(N'db_datareader', N'enquiries_app') = 0 ALTER ROLE db_datareader ADD MEMBER enquiries_app;
IF IS_ROLEMEMBER(N'db_datawriter', N'enquiries_app') = 0 ALTER ROLE db_datawriter ADD MEMBER enquiries_app;
GO

PRINT 'db/init.sql: databases, logins and users are in place.';

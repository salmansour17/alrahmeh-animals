"""003_ledger_reversals.sql, applied the way it will be on Azure: to a
ledger that already holds gifts.

Each rule of the migration is proven by trying to break it with plain SQL,
straight at the database, and checking SQL Server refuses. The code above the
database keeps these rules too, but the database is the last word: anything
that bypasses the code still meets them.
"""

from __future__ import annotations

import logging
import re
import shutil

import pymssql
import pytest

from db import Database
from donations.models import DonationKind
from migrate import MIGRATIONS_DIR, apply_migrations
from tests.test_migrate import scratch_url  # noqa: F401 (a fixture, used by name)

# SQL Server's error numbers, as the real server reports them.
CONSTRAINT_VIOLATED = 547  # a CHECK or FOREIGN KEY constraint
DUPLICATE_IN_UNIQUE_INDEX = 2601
APPEND_ONLY = 51000  # THROW in tr_donations_append_only (001_init.sql)
COMPUTED_COLUMN = 271

GIFTS_BEFORE_003 = (25_000, 65_000, 255_000)


@pytest.fixture
def ledger(scratch_url, tmp_path) -> Database:  # noqa: F811 (the fixture above)
    """A database at 002 holding three gifts, as Azure's was on 2026-11-26,
    then migrated to the latest version."""
    database = Database.from_url(scratch_url)
    for name in ("001_init.sql", "002_health_probe.sql"):
        shutil.copy(MIGRATIONS_DIR / name, tmp_path / name)
    apply_migrations(database, tmp_path)
    with database.unit_of_work() as connection:
        for amount in GIFTS_BEFORE_003:
            connection.execute(
                "INSERT INTO donations (donor_name, amount_fils, purpose, received_at) VALUES (%s, %s, %s, %s)",
                ("Mo", amount, "medical_fund", "2026-11-26"),
            )
    return database


def _migrate(database: Database) -> list[str]:
    return apply_migrations(database, MIGRATIONS_DIR)


def _insert(database: Database, kind: str, target: int | None, reason: str | None) -> int:
    with database.unit_of_work() as connection:
        row = connection.execute(
            "INSERT INTO donations (amount_fils, purpose, received_at, kind, reverses_donation_id, reversal_reason) "
            "OUTPUT INSERTED.id VALUES (%s, %s, %s, %s, %s, %s)",
            (25_000, "medical_fund", "2026-11-27", kind, target, reason),
        ).fetchone()
    return row["id"]


def _refused(database: Database, sql: str, params: tuple = ()) -> int:
    """Run sql, which must fail, and return SQL Server's error number."""
    with pytest.raises(pymssql.Error) as raised, database.unit_of_work() as connection:
        connection.execute(sql, params)
    return raised.value.args[0]


def test_existing_gifts_become_gifts_without_any_update(ledger, caplog):
    with caplog.at_level(logging.INFO, logger="migrate"):
        assert _migrate(ledger) == ["003_ledger_reversals.sql"]
    # The line the deployment's log step looks for.
    assert f"Applied migration 003_ledger_reversals.sql to {ledger.name}" in caplog.text
    with ledger.unit_of_work() as connection:
        rows = connection.execute(
            "SELECT amount_fils, kind, reverses_donation_id, reversal_reason FROM donations ORDER BY id"
        ).fetchall()
    assert [(r["amount_fils"], r["kind"], r["reverses_donation_id"], r["reversal_reason"]) for r in rows] == [
        (amount, "gift", None, None) for amount in GIFTS_BEFORE_003
    ]


def test_the_migration_file_never_updates_and_never_touches_the_trigger():
    sql = (MIGRATIONS_DIR / "003_ledger_reversals.sql").read_text(encoding="utf-8")
    code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert not re.search(r"\bUPDATE\b", code, re.IGNORECASE)
    assert not re.search(r"\b(DISABLE|ENABLE|ALTER|DROP)\s+TRIGGER\b", code, re.IGNORECASE)


def test_a_second_run_applies_nothing(ledger):
    _migrate(ledger)
    assert _migrate(ledger) == []


def test_the_trigger_still_refuses_updates_and_deletes_on_old_and_new_rows(ledger):
    _migrate(ledger)
    reversal = _insert(ledger, "reversal", 1, "recorded twice")
    for row_id in (1, reversal):
        assert _refused(ledger, "UPDATE donations SET amount_fils = 1 WHERE id = %s", (row_id,)) == APPEND_ONLY
        assert _refused(ledger, "DELETE FROM donations WHERE id = %s", (row_id,)) == APPEND_ONLY
    # Not even to turn a gift into a reversal after the fact.
    assert _refused(ledger, "UPDATE donations SET kind = N'reversal' WHERE id = 2") == APPEND_ONLY


def test_a_gift_can_be_reversed_once_only(ledger):
    _migrate(ledger)
    _insert(ledger, "reversal", 1, "typo")
    with pytest.raises(pymssql.IntegrityError) as raised:
        _insert(ledger, "reversal", 1, "typo again")
    assert raised.value.args[0] == DUPLICATE_IN_UNIQUE_INDEX
    assert "ux_donations_reversed_once" in str(raised.value)


def test_many_gifts_can_coexist_with_no_target(ledger):
    # The "once only" index is filtered: a plain UNIQUE would allow one NULL,
    # that is one gift, in the whole ledger.
    _migrate(ledger)
    _insert(ledger, "gift", None, None)
    _insert(ledger, "gift", None, None)


def test_a_reversal_cannot_reverse_a_reversal(ledger):
    _migrate(ledger)
    reversal = _insert(ledger, "reversal", 1, "typo")
    with pytest.raises(pymssql.IntegrityError) as raised:
        _insert(ledger, "reversal", reversal, "undo the undo")
    assert raised.value.args[0] == CONSTRAINT_VIOLATED
    assert "fk_donations_reverses_gift" in str(raised.value)


def test_a_reversal_must_point_at_a_donation_that_exists(ledger):
    _migrate(ledger)
    with pytest.raises(pymssql.IntegrityError) as raised:
        _insert(ledger, "reversal", 999, "ghost")
    assert raised.value.args[0] == CONSTRAINT_VIOLATED
    assert "fk_donations_reverses_gift" in str(raised.value)


@pytest.mark.parametrize(
    ("kind", "target", "reason"),
    [
        ("reversal", 1, None),  # a reversal needs a reason
        ("reversal", None, "why"),  # and a target
        ("gift", 1, None),  # a gift has no target
        ("gift", None, "why"),  # and no reason
    ],
)
def test_the_row_shape_is_enforced(ledger, kind, target, reason):
    _migrate(ledger)
    with pytest.raises(pymssql.IntegrityError) as raised:
        _insert(ledger, kind, target, reason)
    assert raised.value.args[0] == CONSTRAINT_VIOLATED
    assert "ck_donations_reversal_shape" in str(raised.value)


def test_an_unknown_kind_is_refused(ledger):
    _migrate(ledger)
    with pytest.raises(pymssql.IntegrityError) as raised:
        _insert(ledger, "refund", 1, "why")
    assert "ck_donations_kind" in str(raised.value)


def test_the_target_kind_cannot_be_set_by_hand(ledger):
    _migrate(ledger)
    number = _refused(
        ledger,
        "INSERT INTO donations (amount_fils, purpose, received_at, reverses_kind) "
        "VALUES (1, N'general', '2026-11-27', N'reversal')",
    )
    assert number == COMPUTED_COLUMN


def test_the_kind_enum_matches_the_check_constraint(database):
    with database.unit_of_work() as connection:
        definition = connection.execute(
            "SELECT definition FROM sys.check_constraints WHERE name = N'ck_donations_kind'"
        ).fetchone()["definition"]
    assert set(re.findall(r"N'([a-z]+)'", definition)) == {kind.value for kind in DonationKind}


def test_every_new_constraint_and_index_has_its_own_name(database):
    with database.unit_of_work() as connection:
        rows = connection.execute(
            "SELECT name FROM sys.objects WHERE parent_object_id = OBJECT_ID(N'donations') "
            "UNION ALL SELECT name FROM sys.indexes WHERE object_id = OBJECT_ID(N'donations') AND name IS NOT NULL"
        ).fetchall()
    names = {row["name"] for row in rows}
    assert {
        "df_donations_kind",
        "ck_donations_kind",
        "ck_donations_reversal_shape",
        "uq_donations_id_kind",
        "fk_donations_reverses_gift",
        "ux_donations_reversed_once",
    } <= names
    # SQL Server's generated names look like DF__donations__kind__1A2B3C4D.
    assert not [name for name in names if "__" in name]


def test_a_full_clean_up_of_a_ledger_with_reversals_still_works(ledger):
    # The test fixtures empty the ledger with one DELETE; a table that now
    # points at itself must still allow that in a single statement.
    _migrate(ledger)
    _insert(ledger, "reversal", 1, "typo")
    with ledger.unit_of_work() as connection:
        connection.execute("DISABLE TRIGGER tr_donations_append_only ON donations")
        connection.execute("DELETE FROM donations")
        connection.execute("ENABLE TRIGGER tr_donations_append_only ON donations")
        assert connection.execute("SELECT COUNT(*) AS n FROM donations").fetchone()["n"] == 0

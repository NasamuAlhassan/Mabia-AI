"""The startup migration, against the database it actually runs on.

add_missing_columns runs on every boot. A statement it cannot execute is not a
failed migration, it is a service that does not start -- and Render keeps
serving the last build that did, so the site stays up and every deploy fails
silently. That is how this went unnoticed for three days.
"""
import pytest
from sqlalchemy import Column, DateTime, Boolean, Integer, String, Table, MetaData

from app.migrate import _sql_type


def _postgres():
    try:
        from sqlalchemy.dialects.postgresql import dialect
        return dialect()
    except Exception:                                    # pragma: no cover
        pytest.skip("postgres dialect unavailable")


def _sqlite():
    from sqlalchemy.dialects.sqlite import dialect
    return dialect()


COLUMNS = Table(
    "sample", MetaData(),
    Column("when", DateTime),
    Column("flag", Boolean),
    Column("count", Integer),
    Column("name", String),
)


def test_a_datetime_is_not_rendered_as_DATETIME_on_postgres():
    """The exact statement that stopped the service booting:

        ALTER TABLE emergencies ADD COLUMN nudged_at DATETIME
        -> type "datetime" does not exist
    """
    rendered = _sql_type(COLUMNS.c.when, _postgres())
    assert "DATETIME" not in rendered.upper()
    assert "TIMESTAMP" in rendered.upper()


def test_sqlite_still_gets_sqlite_types():
    assert "DATETIME" in _sql_type(COLUMNS.c.when, _sqlite()).upper()


@pytest.mark.parametrize("name", ["when", "flag", "count", "name"])
def test_every_column_type_compiles_for_both_databases(name):
    """Not just the one that broke. A type that renders on neither is the same
    outage wearing a different column name."""
    for dialect in (_postgres(), _sqlite()):
        rendered = _sql_type(COLUMNS.c[name], dialect)
        assert rendered and rendered != "TEXT" or name == "name"


def test_every_real_model_column_renders_on_postgres():
    """The whole schema, because the next column added is the next outage."""
    from app.db import Base
    postgres = _postgres()
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            rendered = _sql_type(column, postgres)
            assert "DATETIME" not in rendered.upper(), (
                "{}.{} renders as {} — Postgres has no DATETIME".format(
                    table.name, column.name, rendered))

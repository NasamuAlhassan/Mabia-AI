"""Add columns that create_all() cannot.

SQLAlchemy's create_all only ever creates tables that are missing; it never
alters one that already exists. So every column added after a database was
first created is invisible to it, and the first query naming that column fails
with "no such column" -- on a developer's laptop, on any deployment with a
persistent disk, and permanently on the Postgres block render.yaml invites you
to uncomment. The hosted demo only escaped it because Render wipes its free
disk on every deploy.

This is not a migration framework and does not pretend to be one. It adds
missing columns and nothing else: no drops, no type changes, no renames, no
data movement. Anything beyond that needs Alembic and a considered plan, which
is the right tool the moment this carries real patient data.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .db import Base


def _sql_type(column) -> str:
    try:
        return column.type.compile()
    except Exception:
        return "TEXT"


def _default_value(column):
    """The value the models would have used, if it is a plain constant."""
    default = column.default
    if default is None or getattr(default, "is_callable", False):
        return None
    value = getattr(default, "arg", None)
    if callable(value) or isinstance(value, (dict, list)):
        return None
    return value


def _backfill(engine: Engine, table_name: str, column) -> int:
    """Give existing rows the default the models declare. Returns rows touched."""
    value = _default_value(column)
    if value is None:
        return 0
    with engine.begin() as connection:
        result = connection.execute(
            text("UPDATE {} SET {} = :value WHERE {} IS NULL".format(
                table_name, column.name, column.name)),
            {"value": value})
        return result.rowcount or 0


def add_missing_columns(engine: Engine) -> list:
    """Bring an existing database up to the current models. Returns what it did."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue                       # create_all handles whole tables
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            # A NOT NULL column cannot be added to a populated table without a
            # default, and inventing one for clinical data would be worse than
            # failing loudly. Report it and let a human decide.
            if not column.nullable and column.default is None \
                    and column.server_default is None:
                added.append("SKIPPED {}.{} (not-null, no default)".format(
                    table.name, column.name))
                continue

            # ALTER TABLE ADD COLUMN is always nullable here, because a
            # SQLAlchemy `default=` is applied in Python on insert and the
            # database has never heard of it. Adding a NOT NULL column and
            # calling it done left every existing row holding NULL in a column
            # the models promise is never null -- Patient.region among them.
            # So: add it nullable, then backfill the default the models
            # declare, then report honestly which of the two happened.
            statement = "ALTER TABLE {} ADD COLUMN {} {}".format(
                table.name, column.name, _sql_type(column))
            with engine.begin() as connection:
                connection.execute(text(statement))

            filled = _backfill(engine, table.name, column)
            added.append("{}.{}{}".format(
                table.name, column.name,
                " (backfilled {} rows)".format(filled) if filled else ""))

    return added

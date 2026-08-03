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
            statement = "ALTER TABLE {} ADD COLUMN {} {}".format(
                table.name, column.name, _sql_type(column))
            with engine.begin() as connection:
                connection.execute(text(statement))
            added.append("{}.{}".format(table.name, column.name))

    return added

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

            fillable = _default_value(column) is not None
            filled = _backfill(engine, table.name, column)
            if filled:
                note = " (backfilled {} rows)".format(filled)
            elif column.default is not None and not fillable:
                # A callable or a dict/list default cannot be expressed as a
                # constant UPDATE. Saying so is the point: reporting it the
                # same way as "nothing needed filling" is how a column full of
                # NULLs passes for a clean migration.
                note = " (default is computed; existing rows left NULL)"
            else:
                note = ""
            added.append("{}.{}{}".format(table.name, column.name, note))

    added += normalise_stored_phones(engine)
    return added


def normalise_stored_phones(engine: Engine) -> list:
    """Bring numbers written before normalisation existed into one form.

    The ORM listener only fires on insert and update, so rows already on disk
    keep whatever spelling they were saved with until something happens to
    touch them. Every lookup compares against the normalised form, so those
    rows are invisible to it -- and worse than invisible: saving the same
    handset through a form creates a SECOND driver row, and the dispatch
    cascade then rings the same man twice, burning a position in a queue that
    exists for a bleeding woman.
    """
    from .models import _PHONE_COLUMNS
    from .phones import normalise

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    changed = []

    for table, columns in _PHONE_COLUMNS.items():
        if table not in tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column not in have:
                continue
            with engine.begin() as connection:
                rows = connection.execute(text(
                    "SELECT rowid, {0} FROM {1} WHERE {0} IS NOT NULL AND {0} != ''"
                    .format(column, table))).fetchall()
                fixed = 0
                for rowid, value in rows:
                    canonical = normalise(value)
                    if canonical and canonical != value:
                        connection.execute(
                            text("UPDATE {0} SET {1} = :v WHERE rowid = :r"
                                 .format(table, column)),
                            {"v": canonical, "r": rowid})
                        fixed += 1
            if fixed:
                changed.append("{}.{} (normalised {} numbers)".format(
                    table, column, fixed))
    return changed

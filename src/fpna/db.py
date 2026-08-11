import os
from pathlib import Path

import duckdb

from . import config


def get_connection(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the project's DuckDB file."""
    db_path = db_path or config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def run_sql_file(conn: duckdb.DuckDBPyConnection, sql_path: Path) -> None:
    """Execute each ';'-separated statement in a .sql file."""
    statements = [s.strip() for s in sql_path.read_text().split(";") if s.strip()]
    for statement in statements:
        conn.execute(statement)


def _unlink_if_exists(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        path.unlink()
        return True
    except OSError:
        return False


def sync_mirror(conn: duckdb.DuckDBPyConnection, mirror_path: Path | None = None) -> bool:
    """Refresh a standalone copy of `conn`'s database for read-only inspection.

    Why this dance instead of just copying the file: on Windows, DuckDB opens
    DB_PATH with an exclusive lock for as long as `conn` stays open (the
    dashboard holds one connection for its whole run), so a plain file copy -
    or even a second `duckdb.connect(..., read_only=True)` from another
    process - fails with "file is already open in <pid>" while the dashboard
    is up. The only process still allowed to read that data is the one that
    already holds `conn`, so the refresh has to happen from inside it: build
    a fresh copy under a private *.building name, then atomically swap it
    into place, so any other tool can open the public path at any time,
    including while `conn` is still live.

    Two failure modes bit us here before this shape, both against real
    cross-table data (dim_role/workflow_version/workflow_step/
    workflow_instance, linked by foreign keys - not caught by earlier tests
    that only ever wrote to one FK-free table):

    1. `COPY FROM DATABASE ... TO ...` copies tables in name order, not
       dependency order (e.g. "workflow_step" sorts before
       "workflow_version", the table it references) - so it can trip the
       target's own foreign key check mid-copy. Copying table-by-table with
       `CREATE TABLE ... AS SELECT` instead never applies the source's
       keys/constraints to the copy at all, so copy order can never violate
       anything.
    2. Once one statement inside that failed, DuckDB marked the whole
       transaction aborted - and because that transaction lives on `conn`,
       *every other callback* sharing it (the entire dashboard) broke with
       "Current transaction is aborted (please ROLLBACK)" until something
       issued a ROLLBACK. Nothing here may let that escape uncaught, however
       it fails.

    Building under *.building and swapping in with `os.replace` (atomic on
    both Windows and POSIX) instead of deleting/rebuilding the public path
    in place also fixes a second bug: a viewer tool with the mirror file
    already open could catch it mid-rebuild and see an empty database. With
    the swap, an already-open viewer just keeps its consistent (if one cycle
    stale) view until it reopens the file; it never observes a half-built one.
    """
    mirror_path = mirror_path or config.MIRROR_DB_PATH
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    build_path = mirror_path.with_name(mirror_path.name + ".building")
    build_wal = build_path.with_name(build_path.name + ".wal")

    if not (_unlink_if_exists(build_path) and _unlink_if_exists(build_wal)):
        return False  # a leftover build from a previous crashed cycle is stuck open; try again later

    # Clears any attachment a previous, abnormally-ended call left on `conn`
    # under this alias, so the ATTACH below can never fail with "already
    # attached".
    try:
        conn.execute('DETACH "fpna_mirror_build"')
    except duckdb.Error:
        pass

    primary_alias = conn.execute("PRAGMA database_list").fetchall()[0][1]
    escaped_path = str(build_path).replace("'", "''")
    try:
        conn.execute(f"ATTACH '{escaped_path}' AS \"fpna_mirror_build\"")
        tables = conn.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = ?", [primary_alias]
        ).fetchall()
        for (table,) in tables:
            qtable = table.replace('"', '""')
            conn.execute(f'CREATE TABLE "fpna_mirror_build"."{qtable}" AS SELECT * FROM "{qtable}"')
        conn.execute('DETACH "fpna_mirror_build"')
    except Exception:
        # Whatever broke above, `conn` must come out of this usable for
        # every *other* callback - see point 2 in the docstring.
        try:
            conn.execute("ROLLBACK")
        except duckdb.Error:
            pass
        try:
            conn.execute('DETACH "fpna_mirror_build"')
        except duckdb.Error:
            pass
        _unlink_if_exists(build_path)
        _unlink_if_exists(build_wal)
        return False

    try:
        os.replace(build_path, mirror_path)
    except OSError:
        _unlink_if_exists(build_path)
        return False  # mirror_path is locked against replacement right now; retry next tick
    # Best-effort: a .wal can only linger here from an old crashed cycle,
    # since a normal DETACH above always checkpoints build_path first - but
    # if one did, it must not survive to be replayed against today's swap.
    _unlink_if_exists(mirror_path.with_name(mirror_path.name + ".wal"))
    return True

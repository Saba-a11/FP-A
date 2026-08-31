"""Builds the schema and loads the default role palette.

Usage: python -m fpna.seed
"""

import csv

import duckdb

from . import config, db


def run_seed(db_path=None) -> duckdb.DuckDBPyConnection:
    conn = db.get_connection(db_path)
    db.run_sql_file(conn, config.SQL_DIR / "schema.sql")

    existing = conn.execute("SELECT count(*) FROM dim_role").fetchone()[0]
    if existing == 0:
        with open(config.SEED_DIR / "roles.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                conn.execute(
                    "INSERT INTO dim_role (role_code, role_name, color_hex) VALUES (?, ?, ?)",
                    [row["role_code"], row["role_name"], row["color_hex"]],
                )
        print(f"Loaded {existing} -> {conn.execute('SELECT count(*) FROM dim_role').fetchone()[0]} roles")
    else:
        print(f"dim_role already has {existing} rows - skipped seeding")

    retranslate_seeded_role_names(conn)
    unfreeze_default_step_labels(conn)
    migrate_eligibility_to_acceptance_criteria(conn)
    backfill_instance_step_states(conn)

    # Everything above is schema DDL and one-time migrations, and DuckDB
    # cannot replay that kind of WAL entry after an abrupt exit - the
    # database becomes unopenable. Flush it into the file now, while we
    # still can, rather than leaving the whole session exposed. See
    # db.checkpoint for the reproduction.
    db.checkpoint(conn)

    return conn


# roles.csv's role_name values moved from English to Persian (dashboard's UI
# translation) after some databases had already been seeded from the old
# English CSV - re-running the CSV insert above only ever fires on an empty
# dim_role, so an already-seeded database would otherwise be stuck showing
# the old English names forever. This runs every startup and is idempotent
# (matches by the stable role_code, not by name), so it's a no-op once a
# database is already on the current labels.
_SEEDED_ROLE_NAME_FA = {
    "PREPARER": "تهیه‌کننده",
    "DEPT_HEAD": "مدیر بخش",
    "FIN_REVIEWER": "بازبین مالی",
    "CONTROLLER": "کنترلر مالی",
    # CFO intentionally excluded - kept as-is, it reads the same in any language.
}


def retranslate_seeded_role_names(conn: duckdb.DuckDBPyConnection) -> None:
    for role_code, role_name_fa in _SEEDED_ROLE_NAME_FA.items():
        conn.execute(
            "UPDATE dim_role SET role_name = ? WHERE role_code = ? AND role_name != ?",
            [role_name_fa, role_code, role_name_fa],
        )


# dragdrop.js snapshots a role's *current* name into workflow_step.label the
# moment a chip is dropped on the canvas (schema.sql: "label ... falls back
# to the role's name if null") - so steps added before the rename above kept
# showing the old English text forever, even after dim_role.role_name went
# Persian, since get_version()'s "label or role_name" join always prefers a
# non-null label. Only clears a label that *exactly* matches one of the old
# defaults, so a label the user genuinely typed on purpose is never touched.
_OLD_DEFAULT_ROLE_LABELS = ("Preparer", "Department Head", "Finance Reviewer", "Controller")


def unfreeze_default_step_labels(conn: duckdb.DuckDBPyConnection) -> None:
    placeholders = ", ".join("?" for _ in _OLD_DEFAULT_ROLE_LABELS)
    conn.execute(
        f"UPDATE workflow_step SET label = NULL WHERE label IN ({placeholders})",
        list(_OLD_DEFAULT_ROLE_LABELS),
    )


# eligibility (شرایط احراز - who's qualified to hold the role) was replaced
# by acceptance_criteria (شرایط پذیرش خروجی - what makes a submitted output
# acceptable) - schema.sql only ever ADDs acceptance_criteria going forward,
# so a database still carrying the old column needs its data carried over
# once. Runs every startup, like retranslate_seeded_role_names above; a
# no-op (one cheap information_schema lookup) once the old column is gone.
def migrate_eligibility_to_acceptance_criteria(conn: duckdb.DuckDBPyConnection) -> None:
    has_old_column = conn.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'workflow_step' AND column_name = 'eligibility'"
    ).fetchone()[0]
    if not has_old_column:
        return
    conn.execute(
        "UPDATE workflow_step SET acceptance_criteria = eligibility "
        "WHERE acceptance_criteria IS NULL AND eligibility IS NOT NULL"
    )
    conn.execute("ALTER TABLE workflow_step DROP COLUMN eligibility")
    print("Migrated workflow_step.eligibility -> acceptance_criteria and dropped the old column")


# Progress used to live in a single workflow_instance.current_step_id
# pointer; it now lives one row per (instance, step) in
# workflow_instance_step_state, so a stage can hold several parallel steps
# (see sql/schema.sql). An already-running database has instances with a
# pointer but no state rows - this translates the pointer once: everything
# in a stage *before* the pointer's stage counts as already approved,
# everything from that stage on stays pending. Only touches instances that
# have no state rows at all, so it's a no-op on every startup after the
# first and can never overwrite real progress.
def backfill_instance_step_states(conn: duckdb.DuckDBPyConnection) -> None:
    instances = conn.execute(
        """
        SELECT i.instance_id, i.version_id, i.current_step_id
        FROM workflow_instance i
        WHERE NOT EXISTS (
            SELECT 1 FROM workflow_instance_step_state st WHERE st.instance_id = i.instance_id
        )
        """
    ).fetchall()
    if not instances:
        return

    for instance_id, version_id, current_step_id in instances:
        steps = conn.execute(
            "SELECT step_id, step_order FROM workflow_step WHERE version_id = ? ORDER BY step_order",
            [version_id],
        ).fetchall()
        current_stage = next(
            (stage for step_id, stage in steps if step_id == current_step_id),
            None,
        )
        for step_id, stage in steps:
            already_done = current_stage is not None and stage < current_stage
            conn.execute(
                "INSERT INTO workflow_instance_step_state (instance_id, step_id, state) VALUES (?, ?, ?)",
                [instance_id, step_id, "approved" if already_done else "pending"],
            )
    print(f"Backfilled step states for {len(instances)} existing instance(s)")


if __name__ == "__main__":
    run_seed()

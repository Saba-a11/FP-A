"""CRUD for the budgeting-workflow designer: roles, versioned step
templates, and running instances that track a current step.

Editing model, on purpose kept simple for a Draft: the canvas always sends
the *whole* ordered step list on save (`save_steps`), which replaces
whatever was there before for that version. There is no per-step diffing -
drag-and-drop reordering, inserting, and removing are all just "here is the
new list," which is far simpler to keep correct than patching individual
moves.
"""

from __future__ import annotations

import duckdb


def list_roles(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        "SELECT role_id, role_code, role_name, color_hex FROM dim_role ORDER BY role_id"
    ).fetchall()
    return [
        {"role_id": r[0], "role_code": r[1], "role_name": r[2], "color_hex": r[3]} for r in rows
    ]


def create_role(conn: duckdb.DuckDBPyConnection, role_code: str, role_name: str, color_hex: str) -> int:
    return conn.execute(
        "INSERT INTO dim_role (role_code, role_name, color_hex) VALUES (?, ?, ?) RETURNING role_id",
        [role_code, role_name, color_hex],
    ).fetchone()[0]


def rename_role(conn: duckdb.DuckDBPyConnection, role_id: int, role_name: str) -> None:
    """Only role_name (the display label) changes - role_code stays put, so
    nothing that already references this role by id/code is affected.
    Steps already dropped onto a canvas keep whatever label they were given
    at drop time regardless (see schema.sql on workflow_step.label) - a
    rename here only changes the palette chip and any step dropped *after*
    the rename, the same "frozen unless null" rule the seed migration
    documents for the built-in roles.
    """
    conn.execute("UPDATE dim_role SET role_name = ? WHERE role_id = ?", [role_name, role_id])


def list_versions(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT v.version_id, v.name, v.status, v.created_at, v.updated_at,
               count(s.step_id) AS step_count
        FROM workflow_version v
        LEFT JOIN workflow_step s ON s.version_id = v.version_id
        GROUP BY v.version_id, v.name, v.status, v.created_at, v.updated_at
        ORDER BY v.version_id DESC
        """
    ).fetchall()
    return [
        {
            "version_id": r[0],
            "name": r[1],
            "status": r[2],
            "created_at": r[3],
            "updated_at": r[4],
            "step_count": r[5],
        }
        for r in rows
    ]


def get_version(conn: duckdb.DuckDBPyConnection, version_id: int) -> dict | None:
    v = conn.execute(
        "SELECT version_id, name, status, created_at, updated_at FROM workflow_version WHERE version_id = ?",
        [version_id],
    ).fetchone()
    if v is None:
        return None
    steps = conn.execute(
        """
        SELECT s.step_id, s.role_id, s.step_order, s.label, r.role_name, r.color_hex
        FROM workflow_step s
        JOIN dim_role r ON r.role_id = s.role_id
        WHERE s.version_id = ?
        ORDER BY s.step_order
        """,
        [version_id],
    ).fetchall()
    return {
        "version_id": v[0],
        "name": v[1],
        "status": v[2],
        "created_at": v[3],
        "updated_at": v[4],
        "steps": [
            {
                "step_id": s[0],
                "role_id": s[1],
                "step_order": s[2],
                "label": s[3] or s[4],
                "role_name": s[4],
                "color_hex": s[5],
            }
            for s in steps
        ],
    }


def create_version(conn: duckdb.DuckDBPyConnection, name: str, created_by: str | None = None) -> int:
    return conn.execute(
        "INSERT INTO workflow_version (name, status, created_by) VALUES (?, 'draft', ?) RETURNING version_id",
        [name, created_by],
    ).fetchone()[0]


def rename_version(conn: duckdb.DuckDBPyConnection, version_id: int, name: str) -> None:
    conn.execute(
        "UPDATE workflow_version SET name = ?, updated_at = current_timestamp WHERE version_id = ?",
        [name, version_id],
    )


def save_steps(conn: duckdb.DuckDBPyConnection, version_id: int, steps: list[dict]) -> None:
    """Replace the full ordered step list for a version.

    `steps` is a list of {role_id, label} in the desired order - this is
    exactly what the drag-and-drop canvas has in hand after any add,
    remove, or reorder, so there is nothing cleverer to diff against.

    Because every step gets a fresh step_id, any running instance of this
    version that was pointing at an old step_id would otherwise dangle -
    this resets those instances back to the new first step rather than
    leaving a broken reference. Editing a template out from under an
    in-progress instance is a real tradeoff, not a hidden bug: it resets
    that instance's progress, so treat "save" on a version with live
    instances as a deliberate reset, the same way XP-A locks an Approved
    Budget version instead of letting an edit invalidate history.
    """
    conn.execute("DELETE FROM workflow_step WHERE version_id = ?", [version_id])
    for order, step in enumerate(steps):
        conn.execute(
            "INSERT INTO workflow_step (version_id, role_id, step_order, label) VALUES (?, ?, ?, ?)",
            [version_id, step["role_id"], order, step.get("label") or None],
        )
    conn.execute(
        "UPDATE workflow_version SET updated_at = current_timestamp WHERE version_id = ?", [version_id]
    )
    new_first_step = conn.execute(
        "SELECT step_id FROM workflow_step WHERE version_id = ? ORDER BY step_order LIMIT 1",
        [version_id],
    ).fetchone()
    new_first_step_id = new_first_step[0] if new_first_step else None
    conn.execute(
        """
        UPDATE workflow_instance
        SET current_step_id = ?, updated_at = current_timestamp
        WHERE version_id = ?
          AND (current_step_id IS NULL OR current_step_id NOT IN (
              SELECT step_id FROM workflow_step WHERE version_id = ?
          ))
        """,
        [new_first_step_id, version_id, version_id],
    )


def activate_version(conn: duckdb.DuckDBPyConnection, version_id: int) -> None:
    """Mark one version as the active template; every other version falls
    back to draft, since only one process should be "the current one" at a
    time (older ones stay around as history, not as live candidates)."""
    conn.execute("UPDATE workflow_version SET status = 'draft' WHERE status = 'active'")
    conn.execute(
        "UPDATE workflow_version SET status = 'active', updated_at = current_timestamp WHERE version_id = ?",
        [version_id],
    )


def create_instance(conn: duckdb.DuckDBPyConnection, version_id: int, name: str) -> int:
    first_step = conn.execute(
        "SELECT step_id FROM workflow_step WHERE version_id = ? ORDER BY step_order LIMIT 1",
        [version_id],
    ).fetchone()
    current_step_id = first_step[0] if first_step else None
    return conn.execute(
        "INSERT INTO workflow_instance (version_id, name, current_step_id) VALUES (?, ?, ?) RETURNING instance_id",
        [version_id, name, current_step_id],
    ).fetchone()[0]


def list_instances(conn: duckdb.DuckDBPyConnection, version_id: int | None = None) -> list[dict]:
    query = """
        SELECT i.instance_id, i.version_id, i.name, i.current_step_id, i.created_at, i.updated_at,
               v.name AS version_name
        FROM workflow_instance i
        JOIN workflow_version v ON v.version_id = i.version_id
    """
    params = []
    if version_id is not None:
        query += " WHERE i.version_id = ?"
        params.append(version_id)
    query += " ORDER BY i.instance_id DESC"
    rows = conn.execute(query, params).fetchall()
    return [
        {
            "instance_id": r[0],
            "version_id": r[1],
            "name": r[2],
            "current_step_id": r[3],
            "created_at": r[4],
            "updated_at": r[5],
            "version_name": r[6],
        }
        for r in rows
    ]


def set_current_step(conn: duckdb.DuckDBPyConnection, instance_id: int, step_id: int) -> None:
    conn.execute(
        "UPDATE workflow_instance SET current_step_id = ?, updated_at = current_timestamp WHERE instance_id = ?",
        [step_id, instance_id],
    )


def rename_instance(conn: duckdb.DuckDBPyConnection, instance_id: int, name: str) -> None:
    conn.execute(
        "UPDATE workflow_instance SET name = ?, updated_at = current_timestamp WHERE instance_id = ?",
        [name, instance_id],
    )


def delete_instance(conn: duckdb.DuckDBPyConnection, instance_id: int) -> None:
    # No FK anywhere else points at workflow_instance, so a plain DELETE is
    # enough - unlike deleting a workflow_step (which save_steps has to
    # reroute any pointing workflow_instance.current_step_id away from
    # first), nothing dangles once an instance itself is gone.
    conn.execute("DELETE FROM workflow_instance WHERE instance_id = ?", [instance_id])

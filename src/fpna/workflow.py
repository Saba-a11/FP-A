"""CRUD for the budgeting-workflow designer: roles, versioned step
templates, running instances that track a current step, and the audit
trail of how each instance got there.

Editing model, on purpose kept simple for a Draft: the canvas always sends
the *whole* ordered step list on save (`save_steps`), which replaces
whatever was there before for that version. There is no per-step diffing
for *order* - drag-and-drop reordering, inserting, and removing are all
just "here is the new list." Step *identity* is a different story: each
step carries a client-side `key` (see dragdrop.js) that's either "s<id>"
(this chip started life as an existing DB row) or "new_..." (added this
session) - save_steps uses that to UPDATE existing rows in place rather
than delete-and-recreate them, specifically so the per-step detail added
below (owner/duty/template file/etc.) survives a Save instead of being
silently wiped every time the canvas is edited.
"""

from __future__ import annotations

import json
import re
import shutil

import duckdb

from . import config


def list_roles(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        "SELECT role_id, role_code, role_name, color_hex, assignee_name, assignee_email "
        "FROM dim_role ORDER BY role_id"
    ).fetchall()
    return [
        {
            "role_id": r[0],
            "role_code": r[1],
            "role_name": r[2],
            "color_hex": r[3],
            "assignee_name": r[4],
            "assignee_email": r[5],
        }
        for r in rows
    ]


def create_role(conn: duckdb.DuckDBPyConnection, role_code: str, role_name: str, color_hex: str) -> int:
    return conn.execute(
        "INSERT INTO dim_role (role_code, role_name, color_hex) VALUES (?, ?, ?) RETURNING role_id",
        [role_code, role_name, color_hex],
    ).fetchone()[0]


def update_role_details(
    conn: duckdb.DuckDBPyConnection,
    role_id: int,
    role_name: str,
    assignee_name: str | None = None,
    assignee_email: str | None = None,
) -> None:
    """role_code deliberately never changes here - it's the stable identity,
    only role_name/assignee_* are ever editable. Steps already dropped onto
    a canvas keep whatever label they were given at drop time regardless
    (see schema.sql on workflow_step.label) - a rename here only changes
    the palette chip and any step dropped *after* the rename, the same
    "frozen unless null" rule the seed migration documents for the
    built-in roles.
    """
    conn.execute(
        "UPDATE dim_role SET role_name = ?, assignee_name = ?, assignee_email = ? WHERE role_id = ?",
        [role_name, assignee_name or None, assignee_email or None, role_id],
    )


def role_step_usage_count(conn: duckdb.DuckDBPyConnection, role_id: int) -> int:
    """How many workflow_step rows (across every version, draft or active)
    still point at this role - checked before delete_role so the caller can
    show a clear "still used by N step(s)" message instead of the raw
    duckdb.ConstraintException the FK on workflow_step.role_id would
    otherwise raise (see sql/schema.sql)."""
    return conn.execute(
        "SELECT count(*) FROM workflow_step WHERE role_id = ?", [role_id]
    ).fetchone()[0]


def delete_role(conn: duckdb.DuckDBPyConnection, role_id: int) -> None:
    """Raises duckdb.ConstraintException if any workflow_step still
    references this role - callers should check role_step_usage_count
    first to give a friendly message instead of surfacing that raw error."""
    conn.execute("DELETE FROM dim_role WHERE role_id = ?", [role_id])


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


_STEP_COLUMNS = """
    s.step_id, s.role_id, s.step_order, s.label, r.role_name, r.color_hex,
    s.owner, s.duty, s.input_desc, s.output_desc, s.acceptance_criteria,
    s.template_path, s.template_original_name, s.sla_days, s.is_optional,
    s.notification_subject, r.assignee_name, r.assignee_email
"""


def _step_row_to_dict(s: tuple) -> dict:
    return {
        "step_id": s[0],
        "role_id": s[1],
        "step_order": s[2],
        "label": s[3] or s[4],
        "role_name": s[4],
        "color_hex": s[5],
        "owner": s[6],
        "duty": s[7],
        "input_desc": s[8],
        "output_desc": s[9],
        "acceptance_criteria": s[10],
        "template_path": s[11],
        "template_original_name": s[12],
        "sla_days": s[13],
        "is_optional": bool(s[14]),
        # notification_subject/assignee_* pulled in specifically for
        # fpna.notify - a step's Telegram message needs both the per-step
        # subject override and who (if anyone) is actually behind the role.
        "notification_subject": s[15],
        "assignee_name": s[16],
        "assignee_email": s[17],
    }


def get_version(conn: duckdb.DuckDBPyConnection, version_id: int) -> dict | None:
    v = conn.execute(
        "SELECT version_id, name, status, created_at, updated_at FROM workflow_version WHERE version_id = ?",
        [version_id],
    ).fetchone()
    if v is None:
        return None
    steps = conn.execute(
        f"""
        SELECT {_STEP_COLUMNS}
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
        "steps": [_step_row_to_dict(s) for s in steps],
    }


def get_step(conn: duckdb.DuckDBPyConnection, step_id: int) -> dict | None:
    row = conn.execute(
        f"""
        SELECT {_STEP_COLUMNS}
        FROM workflow_step s
        JOIN dim_role r ON r.role_id = s.role_id
        WHERE s.step_id = ?
        """,
        [step_id],
    ).fetchone()
    return _step_row_to_dict(row) if row else None


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


_STEP_KEY_RE = re.compile(r"^s(\d+)$")


def save_steps(conn: duckdb.DuckDBPyConnection, version_id: int, steps: list[dict]) -> None:
    """Replace the full ordered step list for a version.

    `steps` is a list of {role_id, label, key} in the desired order - `key`
    is dragdrop.js's client-side id for that chip: "s<step_id>" if it's an
    existing row, "new_..." if it was just dropped this session. A step
    whose key resolves to a row that still exists gets UPDATEd in place
    (keeping its step_id, and therefore keeping owner/duty/template/etc
    intact); everything else is a fresh INSERT. Rows that existed before
    but aren't in the new list anymore are DELETEd (and their uploaded
    template file, if any, cleaned up with them).

    Because a *removed* step's step_id really does stop existing, any
    running instance of this version that was pointing at it would
    otherwise dangle - this resets those instances back to the new first
    step rather than leaving a broken reference. Editing a template out
    from under an in-progress instance is a real tradeoff, not a hidden
    bug: it resets that instance's progress, so treat "save" on a version
    with live instances as a deliberate reset, the same way XP-A locks an
    Approved Budget version instead of letting an edit invalidate history.
    """
    existing_ids = {
        r[0]
        for r in conn.execute(
            "SELECT step_id FROM workflow_step WHERE version_id = ?", [version_id]
        ).fetchall()
    }

    kept_ids: set[int] = set()
    for order, step in enumerate(steps):
        match = _STEP_KEY_RE.match(step.get("key") or "")
        old_step_id = int(match.group(1)) if match else None
        if old_step_id is not None and old_step_id in existing_ids:
            conn.execute(
                "UPDATE workflow_step SET role_id = ?, step_order = ?, label = ? WHERE step_id = ?",
                [step["role_id"], order, step.get("label") or None, old_step_id],
            )
            kept_ids.add(old_step_id)
        else:
            conn.execute(
                "INSERT INTO workflow_step (version_id, role_id, step_order, label) VALUES (?, ?, ?, ?)",
                [version_id, step["role_id"], order, step.get("label") or None],
            )

    for removed_step_id in existing_ids - kept_ids:
        _delete_step_template_dir(removed_step_id)
        conn.execute("DELETE FROM workflow_step WHERE step_id = ?", [removed_step_id])

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


def update_step_details(
    conn: duckdb.DuckDBPyConnection,
    step_id: int,
    owner: str | None,
    duty: str | None,
    input_desc: str | None,
    output_desc: str | None,
    acceptance_criteria: str | None,
    sla_days: int | None,
    is_optional: bool,
    notification_subject: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE workflow_step
        SET owner = ?, duty = ?, input_desc = ?, output_desc = ?, acceptance_criteria = ?,
            sla_days = ?, is_optional = ?, notification_subject = ?
        WHERE step_id = ?
        """,
        [
            owner or None,
            duty or None,
            input_desc or None,
            output_desc or None,
            acceptance_criteria or None,
            sla_days,
            is_optional,
            notification_subject or None,
            step_id,
        ],
    )


def _step_template_dir(step_id: int):
    return config.TEMPLATES_DIR / f"step_{step_id}"


def _delete_step_template_dir(step_id: int) -> None:
    step_dir = _step_template_dir(step_id)
    if step_dir.exists():
        shutil.rmtree(step_dir, ignore_errors=True)


def save_step_template(conn: duckdb.DuckDBPyConnection, step_id: int, filename: str, content_bytes: bytes) -> None:
    """Writes the uploaded file to its own step_<id>/ folder (so two steps
    can each have a file named the same thing without colliding), replacing
    whatever was there before for this step. Only the path *relative to
    PROJECT_ROOT* is stored in the database - never an absolute path - so
    the database file stays portable if this project ever moves machines.
    """
    step_dir = _step_template_dir(step_id)
    _delete_step_template_dir(step_id)
    step_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]+", "_", filename).strip("_") or "template"
    dest = step_dir / safe_name
    dest.write_bytes(content_bytes)
    rel_path = dest.relative_to(config.PROJECT_ROOT).as_posix()
    conn.execute(
        "UPDATE workflow_step SET template_path = ?, template_original_name = ? WHERE step_id = ?",
        [rel_path, filename, step_id],
    )


def clear_step_template(conn: duckdb.DuckDBPyConnection, step_id: int) -> None:
    _delete_step_template_dir(step_id)
    conn.execute(
        "UPDATE workflow_step SET template_path = NULL, template_original_name = NULL WHERE step_id = ?",
        [step_id],
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


def get_or_create_instance(conn: duckdb.DuckDBPyConnection, version_id: int) -> dict:
    """Every workflow version tracks exactly one progress-through-the-steps
    run - there's no user-facing "create an instance" step anymore. This is
    what every caller in callbacks.py uses instead of create_instance +
    list_instances: it returns the version's one instance, silently
    creating it (named after the version itself, parked at its first step
    if it has one yet) the first time this version's progress is ever
    looked at. Idempotent - a version that already has one just gets it
    back, unchanged.

    If the canvas had no steps yet at that first look (current_step_id
    ends up NULL), there's nothing more to reconcile here: save_steps's own
    "reset any instance with no valid current step to the new first step"
    logic (see its docstring) catches this instance up automatically the
    moment real steps are saved for this version, same as it would for a
    stale current_step_id after steps are edited.

    To run two real cycles of the same design at once (e.g. two budget
    years), make a second workflow (version) for the second one - each
    tracks its own independent run. That's the one capability dropped by
    moving off "many named instances per version" - deliberate, per the
    user's own call.
    """
    existing = conn.execute(
        "SELECT instance_id FROM workflow_instance WHERE version_id = ? ORDER BY instance_id LIMIT 1",
        [version_id],
    ).fetchone()
    if existing is None:
        version_row = conn.execute(
            "SELECT name FROM workflow_version WHERE version_id = ?", [version_id]
        ).fetchone()
        create_instance(conn, version_id, version_row[0] if version_row else "گردش‌کار")
    return list_instances(conn, version_id)[0]


def get_instance(conn: duckdb.DuckDBPyConnection, instance_id: int) -> dict | None:
    """Single-instance counterpart to list_instances - used by
    fpna.notify's caller (callbacks.py) to build one notification without
    pulling every instance in the version just to find the one that
    changed.
    """
    row = conn.execute(
        """
        SELECT i.instance_id, i.version_id, i.name, i.current_step_id, i.created_at, i.updated_at,
               v.name AS version_name
        FROM workflow_instance i
        JOIN workflow_version v ON v.version_id = i.version_id
        WHERE i.instance_id = ?
        """,
        [instance_id],
    ).fetchone()
    if row is None:
        return None
    return {
        "instance_id": row[0],
        "version_id": row[1],
        "name": row[2],
        "current_step_id": row[3],
        "created_at": row[4],
        "updated_at": row[5],
        "version_name": row[6],
    }


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


def set_current_step(
    conn: duckdb.DuckDBPyConnection,
    instance_id: int,
    step_id: int,
    note: str | None = None,
    actor: str | None = None,
) -> str:
    """Moves an instance to `step_id` and logs the move to
    workflow_instance_history - every click that changes an instance's
    current step is audited automatically, no extra step required. `action`
    is inferred from step_order: moving to an earlier step than the one you
    were on is logged as a "reject" (a formal send-back), anything else as
    an "advance". There's no login system in this app, so `actor` is
    whatever the user optionally typed, not an authenticated identity.

    Returns that same `action` ("advance" | "reject") so callers - notably
    callbacks.py, sending the step-change notification right after this
    call - don't have to re-derive it from step_order themselves.
    """
    row = conn.execute(
        "SELECT current_step_id, version_id FROM workflow_instance WHERE instance_id = ?", [instance_id]
    ).fetchone()
    from_step_id = row[0] if row else None
    version_id = row[1] if row else None

    action = "advance"
    if from_step_id is not None and version_id is not None and from_step_id != step_id:
        orders = dict(
            conn.execute(
                "SELECT step_id, step_order FROM workflow_step WHERE version_id = ? AND step_id IN (?, ?)",
                [version_id, from_step_id, step_id],
            ).fetchall()
        )
        if step_id in orders and from_step_id in orders and orders[step_id] < orders[from_step_id]:
            action = "reject"

    conn.execute(
        "UPDATE workflow_instance SET current_step_id = ?, updated_at = current_timestamp WHERE instance_id = ?",
        [step_id, instance_id],
    )
    conn.execute(
        """
        INSERT INTO workflow_instance_history (instance_id, from_step_id, to_step_id, action, note, actor)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [instance_id, from_step_id, step_id, action, note or None, actor or None],
    )
    return action


def skip_current_step(conn: duckdb.DuckDBPyConnection, instance_id: int) -> int | None:
    """Advances an instance past its current step without needing that
    role's action - only when the current step is marked optional
    (workflow_step.is_optional). Returns None (a no-op the caller should
    surface as a message) if the current step isn't optional, or there's no
    next step to move to - otherwise the new current_step_id, so callers -
    notably callbacks.py, sending the step-change notification right after
    this call - don't have to look it back up.
    """
    row = conn.execute(
        """
        SELECT i.current_step_id, i.version_id, s.step_order, s.is_optional
        FROM workflow_instance i
        LEFT JOIN workflow_step s ON s.step_id = i.current_step_id
        WHERE i.instance_id = ?
        """,
        [instance_id],
    ).fetchone()
    if row is None or row[0] is None or not row[3]:
        return None
    current_step_id, version_id, step_order, _ = row
    next_step = conn.execute(
        "SELECT step_id FROM workflow_step WHERE version_id = ? AND step_order > ? ORDER BY step_order LIMIT 1",
        [version_id, step_order],
    ).fetchone()
    if next_step is None:
        return None
    conn.execute(
        "UPDATE workflow_instance SET current_step_id = ?, updated_at = current_timestamp WHERE instance_id = ?",
        [next_step[0], instance_id],
    )
    conn.execute(
        "INSERT INTO workflow_instance_history (instance_id, from_step_id, to_step_id, action) VALUES (?, ?, ?, 'skip')",
        [instance_id, current_step_id, next_step[0]],
    )
    return next_step[0]


def add_history_note(conn: duckdb.DuckDBPyConnection, history_id: int, note: str) -> None:
    conn.execute("UPDATE workflow_instance_history SET note = ? WHERE history_id = ?", [note, history_id])


def list_instance_history(conn: duckdb.DuckDBPyConnection, instance_id: int) -> list[dict]:
    # LEFT JOIN on both sides, not an inner join: a step referenced by an
    # old history row can since have been removed from the canvas (nothing
    # enforces current_step_id as a hard FK - see schema.sql), and the
    # audit trail must never silently lose a row just because the step it
    # names doesn't exist anymore.
    rows = conn.execute(
        """
        SELECT h.history_id, h.action, h.note, h.actor, h.created_at,
               COALESCE(fs.label, fr.role_name) AS from_label,
               COALESCE(ts.label, tr.role_name) AS to_label
        FROM workflow_instance_history h
        LEFT JOIN workflow_step fs ON fs.step_id = h.from_step_id
        LEFT JOIN dim_role fr ON fr.role_id = fs.role_id
        LEFT JOIN workflow_step ts ON ts.step_id = h.to_step_id
        LEFT JOIN dim_role tr ON tr.role_id = ts.role_id
        WHERE h.instance_id = ?
        ORDER BY h.history_id DESC
        """,
        [instance_id],
    ).fetchall()
    return [
        {
            "history_id": r[0],
            "action": r[1],
            "note": r[2],
            "actor": r[3],
            "created_at": r[4],
            "from_label": r[5],
            "to_label": r[6] or "مرحله‌ی حذف‌شده",
        }
        for r in rows
    ]


def rename_instance(conn: duckdb.DuckDBPyConnection, instance_id: int, name: str) -> None:
    conn.execute(
        "UPDATE workflow_instance SET name = ?, updated_at = current_timestamp WHERE instance_id = ?",
        [name, instance_id],
    )


def delete_instance(conn: duckdb.DuckDBPyConnection, instance_id: int) -> None:
    # workflow_instance_history rows reference this instance_id but aren't a
    # hard FK either (same "validated in code, not schema" reasoning as
    # current_step_id) - deleting them explicitly here keeps the history
    # table from accumulating rows about instances that no longer exist.
    conn.execute("DELETE FROM workflow_instance_history WHERE instance_id = ?", [instance_id])
    conn.execute("DELETE FROM workflow_instance WHERE instance_id = ?", [instance_id])


def step_status_summary(conn: duckdb.DuckDBPyConnection, version_id: int) -> list[dict]:
    """Per-step instance counts for one version - drives the pending-work
    summary panel: how many running instances are sitting at each step
    right now, who (if anyone) is assigned to that role, and how many of
    those are overdue against the step's own sla_days. This is deliberately
    scoped to one version rather than "all instances everywhere," matching
    every other view in this app (see _load_view).
    """
    rows = conn.execute(
        """
        SELECT s.step_id, s.step_order, COALESCE(s.label, r.role_name) AS label,
               r.color_hex, r.assignee_name, r.assignee_email, s.sla_days,
               count(i.instance_id) AS pending_count,
               count(*) FILTER (
                   WHERE s.sla_days IS NOT NULL
                     AND date_diff('day', i.updated_at, current_timestamp) > s.sla_days
               ) AS overdue_count
        FROM workflow_step s
        JOIN dim_role r ON r.role_id = s.role_id
        LEFT JOIN workflow_instance i ON i.current_step_id = s.step_id
        WHERE s.version_id = ?
        GROUP BY s.step_id, s.step_order, s.label, r.role_name, r.color_hex, r.assignee_name, r.assignee_email, s.sla_days
        ORDER BY s.step_order
        """,
        [version_id],
    ).fetchall()
    return [
        {
            "step_id": r[0],
            "step_order": r[1],
            "label": r[2],
            "color_hex": r[3],
            "assignee_name": r[4],
            "assignee_email": r[5],
            "sla_days": r[6],
            "pending_count": r[7],
            "overdue_count": r[8],
        }
        for r in rows
    ]


def export_version_json(conn: duckdb.DuckDBPyConnection, version_id: int) -> str:
    """A portable snapshot of one version's steps, keyed by role *name*
    (not role_id, which won't line up on a different database) - see
    import_version_json. Uploaded template files are intentionally left
    out: they'd bloat this into a binary blob instead of a readable JSON
    file, so exporting/importing across databases only carries the step
    structure and text detail, not the attached files.
    """
    version = get_version(conn, version_id)
    if version is None:
        return "{}"
    payload = {
        "name": version["name"],
        "steps": [
            {
                "role_name": s["role_name"],
                "label": s["label"] if s["label"] != s["role_name"] else None,
                "owner": s["owner"],
                "duty": s["duty"],
                "input_desc": s["input_desc"],
                "output_desc": s["output_desc"],
                "acceptance_criteria": s["acceptance_criteria"],
                "sla_days": s["sla_days"],
                "is_optional": s["is_optional"],
                "notification_subject": s["notification_subject"],
            }
            for s in version["steps"]
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def import_version_json(
    conn: duckdb.DuckDBPyConnection, payload: dict, name_override: str | None = None
) -> tuple[int, list[str]]:
    """Creates a brand-new version (never overwrites an existing one) from
    a payload shaped like export_version_json's output. A step whose
    role_name doesn't exist in *this* database is skipped rather than
    guessed at - see the returned skipped_roles use in callbacks.py, which
    surfaces that to the user instead of silently dropping steps.
    """
    name = name_override or payload.get("name") or "نسخه‌ی وارد شده"
    version_id = create_version(conn, name)
    roles_by_name = {r["role_name"]: r for r in list_roles(conn)}
    order = 0
    skipped_roles = []
    for step in payload.get("steps", []):
        role = roles_by_name.get(step.get("role_name"))
        if role is None:
            skipped_roles.append(step.get("role_name"))
            continue
        step_id = conn.execute(
            "INSERT INTO workflow_step (version_id, role_id, step_order, label) VALUES (?, ?, ?, ?) RETURNING step_id",
            [version_id, role["role_id"], order, step.get("label") or None],
        ).fetchone()[0]
        update_step_details(
            conn,
            step_id,
            step.get("owner"),
            step.get("duty"),
            step.get("input_desc"),
            step.get("output_desc"),
            step.get("acceptance_criteria"),
            step.get("sla_days"),
            bool(step.get("is_optional")),
            step.get("notification_subject"),
        )
        order += 1
    return version_id, skipped_roles

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
from datetime import datetime

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
    s.notification_subject, r.assignee_name, r.assignee_email,
    COALESCE(s.lane, 0)
"""


def _step_row_to_dict(s: tuple) -> dict:
    return {
        "step_id": s[0],
        "role_id": s[1],
        # "stage" is the real name of this concept now that a stage can hold
        # several parallel steps (see sql/schema.sql on step_order). The old
        # "step_order" key is kept as an alias so nothing that still reads it
        # breaks - both always carry the same value.
        "step_order": s[2],
        "stage": s[2],
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
        "lane": s[18],
    }


def group_into_stages(steps: list[dict]) -> list[list[dict]]:
    """Regroups a flat, (stage, lane)-ordered step list into one list per
    stage - the shape the canvas renders as columns and the instance track
    renders as parallel rows. Stage numbers are used only for grouping and
    ordering here, never as indexes, so a version whose stages aren't
    contiguous (0, 1, 3 - possible mid-edit) still groups correctly.
    """
    stages: list[list[dict]] = []
    current_stage = None
    for step in steps:
        if step["stage"] != current_stage:
            stages.append([])
            current_stage = step["stage"]
        stages[-1].append(step)
    return stages


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
        ORDER BY s.step_order, COALESCE(s.lane, 0), s.step_id
        """,
        [version_id],
    ).fetchall()
    step_dicts = [_step_row_to_dict(s) for s in steps]
    return {
        "version_id": v[0],
        "name": v[1],
        "status": v[2],
        "created_at": v[3],
        "updated_at": v[4],
        # Flat list (every caller that just wants "all the steps"), plus the
        # same steps grouped by stage for the canvas/track - one query, two
        # shapes, so the two can never disagree about ordering.
        "steps": step_dicts,
        "stages": group_into_stages(step_dicts),
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

    `steps` is a list of {role_id, label, key, stage, lane} - `key` is
    dragdrop.js's client-side id for that chip: "s<step_id>" if it's an
    existing row, "new_..." if it was just dropped this session. A step
    whose key resolves to a row that still exists gets UPDATEd in place
    (keeping its step_id, and therefore keeping owner/duty/template/etc
    intact); everything else is a fresh INSERT. Rows that existed before
    but aren't in the new list anymore are DELETEd (and their uploaded
    template file, if any, cleaned up with them).

    `stage` is which canvas column the chip sits in - several steps sharing
    one stage are that stage's parallel branches (see sql/schema.sql). It's
    renumbered to a dense 0..n-1 here from the order the stages first
    appear, so a design edited down to fewer columns never leaves gaps.
    Missing `stage` falls back to the chip's position, which is exactly the
    old one-step-per-stage linear behaviour.

    Removing a step really does delete its step_id, so any running instance
    holding progress against it would dangle - sync_instance_states below
    reconciles every instance of this version afterwards (drops orphaned
    rows, adds rows for new steps). Progress on steps that survived the
    edit is preserved; only what no longer exists is dropped.
    """
    existing_ids = {
        r[0]
        for r in conn.execute(
            "SELECT step_id FROM workflow_step WHERE version_id = ?", [version_id]
        ).fetchall()
    }

    # Dense-renumber the stages by first appearance, so the stored step_order
    # is always 0..n-1 with no holes regardless of what the client sent.
    stage_numbers: dict = {}
    for position, step in enumerate(steps):
        raw_stage = step.get("stage")
        if raw_stage is None:
            raw_stage = position
        if raw_stage not in stage_numbers:
            stage_numbers[raw_stage] = len(stage_numbers)

    kept_ids: set[int] = set()
    for position, step in enumerate(steps):
        raw_stage = step.get("stage")
        if raw_stage is None:
            raw_stage = position
        stage = stage_numbers[raw_stage]
        lane = step.get("lane") or 0
        match = _STEP_KEY_RE.match(step.get("key") or "")
        old_step_id = int(match.group(1)) if match else None
        if old_step_id is not None and old_step_id in existing_ids:
            conn.execute(
                "UPDATE workflow_step SET role_id = ?, step_order = ?, lane = ?, label = ? WHERE step_id = ?",
                [step["role_id"], stage, lane, step.get("label") or None, old_step_id],
            )
            kept_ids.add(old_step_id)
        else:
            conn.execute(
                "INSERT INTO workflow_step (version_id, role_id, step_order, lane, label) VALUES (?, ?, ?, ?, ?)",
                [version_id, step["role_id"], stage, lane, step.get("label") or None],
            )

    for removed_step_id in existing_ids - kept_ids:
        _delete_step_template_dir(removed_step_id)
        conn.execute("DELETE FROM workflow_step WHERE step_id = ?", [removed_step_id])

    conn.execute(
        "UPDATE workflow_version SET updated_at = current_timestamp WHERE version_id = ?", [version_id]
    )
    for row in conn.execute(
        "SELECT instance_id FROM workflow_instance WHERE version_id = ?", [version_id]
    ).fetchall():
        sync_instance_states(conn, row[0], version_id)


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
        instance_id = create_instance(conn, version_id, version_row[0] if version_row else "گردش‌کار")
    else:
        instance_id = existing[0]
    sync_instance_states(conn, instance_id, version_id)
    return list_instances(conn, version_id)[0]


# ---- Instance progress across parallel stages ----
#
# The engine that replaced the single current_step_id pointer. Three states
# per (instance, step) - see sql/schema.sql's workflow_instance_step_state -
# and exactly one derived rule on top of them:
#
#     a step is ACTIONABLE  <=>  it is not approved yet
#                                AND every step in the previous stage is
#                                approved (stage 0 has no previous stage,
#                                so it is actionable from the start).
#
# Everything the UI shows (who can act now, which stage is done, whether the
# workflow is finished) falls out of that one rule, so there is no second
# place where "where are we" is decided and no way for the two to disagree.

STATE_PENDING = "pending"
STATE_APPROVED = "approved"
STATE_REJECTED = "rejected"


def sync_instance_states(conn: duckdb.DuckDBPyConnection, instance_id: int, version_id: int) -> None:
    """Reconciles one instance's state rows against its version's current
    steps: adds a pending row for every step that doesn't have one, drops
    rows for steps that no longer exist (save_steps can delete a step - see
    the "no FK on step_id" note in sql/schema.sql). Progress on steps that
    survived an edit is left untouched, so redesigning a stage the workflow
    has already passed doesn't silently rewind the parts that were done.

    Idempotent, and called from both save_steps and get_or_create_instance,
    so any path that can change the step list also repairs state on the way
    through - there's no separate "remember to sync" step to forget.
    """
    step_ids = [
        r[0]
        for r in conn.execute(
            "SELECT step_id FROM workflow_step WHERE version_id = ?", [version_id]
        ).fetchall()
    ]
    existing = {
        r[0]
        for r in conn.execute(
            "SELECT step_id FROM workflow_instance_step_state WHERE instance_id = ?", [instance_id]
        ).fetchall()
    }
    for step_id in step_ids:
        if step_id not in existing:
            conn.execute(
                "INSERT INTO workflow_instance_step_state (instance_id, step_id, state) VALUES (?, ?, ?)",
                [instance_id, step_id, STATE_PENDING],
            )
    for orphan_id in existing - set(step_ids):
        conn.execute(
            "DELETE FROM workflow_instance_step_state WHERE instance_id = ? AND step_id = ?",
            [instance_id, orphan_id],
        )
    _refresh_current_step_pointer(conn, instance_id, version_id)


def instance_step_states(conn: duckdb.DuckDBPyConnection, instance_id: int) -> dict:
    rows = conn.execute(
        "SELECT step_id, state, note, actor, updated_at FROM workflow_instance_step_state WHERE instance_id = ?",
        [instance_id],
    ).fetchall()
    return {r[0]: {"state": r[1], "note": r[2], "actor": r[3], "updated_at": r[4]} for r in rows}


def instance_progress(conn: duckdb.DuckDBPyConnection, instance_id: int, version_id: int) -> dict:
    """The single read model for "where is this workflow right now" - every
    view (the track, the status summary, the notifications) reads this
    rather than re-deriving the rule above for itself.

    Returns the version's stages with each step annotated with its state and
    whether it's actionable, plus per-stage completion flags, the flat set
    of actionable step ids, and is_complete for the whole run.
    """
    version = get_version(conn, version_id)
    stages = version["stages"] if version else []
    states = instance_step_states(conn, instance_id)

    stage_complete = [
        all(states.get(s["step_id"], {}).get("state") == STATE_APPROVED for s in stage)
        for stage in stages
    ]

    annotated_stages = []
    actionable_ids: set = set()
    for index, stage in enumerate(stages):
        previous_done = index == 0 or stage_complete[index - 1]
        annotated = []
        for step in stage:
            state = states.get(step["step_id"], {})
            step_state = state.get("state") or STATE_PENDING
            is_actionable = previous_done and step_state != STATE_APPROVED
            if is_actionable:
                actionable_ids.add(step["step_id"])
            annotated.append(
                {
                    **step,
                    "state": step_state,
                    "state_note": state.get("note"),
                    "state_actor": state.get("actor"),
                    "state_updated_at": state.get("updated_at"),
                    "is_actionable": is_actionable,
                    "stage_index": index,
                }
            )
        annotated_stages.append(annotated)

    return {
        "stages": annotated_stages,
        "stage_complete": stage_complete,
        "actionable_ids": actionable_ids,
        "is_complete": bool(stages) and all(stage_complete),
    }


def _refresh_current_step_pointer(conn: duckdb.DuckDBPyConnection, instance_id: int, version_id: int) -> None:
    """Keeps the legacy workflow_instance.current_step_id column pointing at
    the first actionable step. Nothing decides anything from it any more
    (see sql/schema.sql) - it's maintained only so any reader that hasn't
    moved to instance_progress yet still sees something truthful rather
    than a stale id from before parallel stages existed.
    """
    progress = instance_progress(conn, instance_id, version_id)
    first_actionable = None
    for stage in progress["stages"]:
        for step in stage:
            if step["is_actionable"]:
                first_actionable = step["step_id"]
                break
        if first_actionable is not None:
            break
    conn.execute(
        "UPDATE workflow_instance SET current_step_id = ?, updated_at = current_timestamp WHERE instance_id = ?",
        [first_actionable, instance_id],
    )


def _version_id_of_instance(conn: duckdb.DuckDBPyConnection, instance_id: int) -> int | None:
    row = conn.execute(
        "SELECT version_id FROM workflow_instance WHERE instance_id = ?", [instance_id]
    ).fetchone()
    return row[0] if row else None


def _set_step_state(
    conn: duckdb.DuckDBPyConnection,
    instance_id: int,
    step_id: int,
    state: str,
    note: str | None = None,
    actor: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE workflow_instance_step_state
        SET state = ?, note = ?, actor = ?, updated_at = current_timestamp
        WHERE instance_id = ? AND step_id = ?
        """,
        [state, note, actor, instance_id, step_id],
    )


def _log_history(
    conn: duckdb.DuckDBPyConnection,
    instance_id: int,
    from_step_id: int | None,
    to_step_id: int,
    action: str,
    note: str | None = None,
    actor: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO workflow_instance_history (instance_id, from_step_id, to_step_id, action, note, actor)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [instance_id, from_step_id, to_step_id, action, note or None, actor or None],
    )


def _advance_result(
    conn: duckdb.DuckDBPyConnection,
    instance_id: int,
    version_id: int,
    before_actionable: set,
    acted_step_id: int,
) -> dict:
    """Shared tail of approve_step/skip_step: recomputes progress and reports
    which steps just *became* actionable, i.e. exactly the people who need a
    notification now. Computing it as a set difference rather than "the next
    stage's steps" is what makes it correct for a parallel stage: approving
    the 2nd of 3 branches opens nothing and notifies nobody, approving the
    3rd opens the whole next stage at once.
    """
    after = instance_progress(conn, instance_id, version_id)
    newly_actionable_ids = after["actionable_ids"] - before_actionable - {acted_step_id}
    newly_actionable = [
        step
        for stage in after["stages"]
        for step in stage
        if step["step_id"] in newly_actionable_ids
    ]
    return {
        "ok": True,
        "reason": None,
        "newly_actionable": newly_actionable,
        "is_complete": after["is_complete"],
        "progress": after,
    }


def approve_step(
    conn: duckdb.DuckDBPyConnection, instance_id: int, step_id: int, actor: str | None = None
) -> dict:
    """One person signs off on their own step and hands it forward.

    Refuses unless the step is currently actionable, which is what enforces
    "you can only approve your own step, and only when it's actually your
    turn" - the rule the UI also draws (no button on a step that isn't
    yours), checked here too so it holds regardless of what the client
    sends.
    """
    version_id = _version_id_of_instance(conn, instance_id)
    if version_id is None:
        return {"ok": False, "reason": "نمونه یافت نشد.", "newly_actionable": [], "is_complete": False}

    before = instance_progress(conn, instance_id, version_id)
    if step_id not in before["actionable_ids"]:
        return {
            "ok": False,
            "reason": "این مرحله در حال حاضر قابل تایید نیست.",
            "newly_actionable": [],
            "is_complete": before["is_complete"],
        }

    _set_step_state(conn, instance_id, step_id, STATE_APPROVED, note=None, actor=actor)
    _log_history(conn, instance_id, step_id, step_id, "approve", actor=actor)
    result = _advance_result(conn, instance_id, version_id, before["actionable_ids"], step_id)
    _refresh_current_step_pointer(conn, instance_id, version_id)
    return result


def skip_step(conn: duckdb.DuckDBPyConnection, instance_id: int, step_id: int) -> dict:
    """Same forward move as approve_step, for a step flagged is_optional -
    bypassed without that role having to act. Logged as 'skip' so the audit
    trail distinguishes "they approved it" from "nobody had to".
    """
    version_id = _version_id_of_instance(conn, instance_id)
    if version_id is None:
        return {"ok": False, "reason": "نمونه یافت نشد.", "newly_actionable": [], "is_complete": False}

    before = instance_progress(conn, instance_id, version_id)
    if step_id not in before["actionable_ids"]:
        return {
            "ok": False,
            "reason": "این مرحله در حال حاضر قابل رد کردن نیست.",
            "newly_actionable": [],
            "is_complete": before["is_complete"],
        }
    step = get_step(conn, step_id)
    if step is None or not step["is_optional"]:
        return {
            "ok": False,
            "reason": "این مرحله اختیاری نیست و نمی‌توان آن را رد کرد.",
            "newly_actionable": [],
            "is_complete": before["is_complete"],
        }

    _set_step_state(conn, instance_id, step_id, STATE_APPROVED, note=None, actor=None)
    _log_history(conn, instance_id, step_id, step_id, "skip")
    result = _advance_result(conn, instance_id, version_id, before["actionable_ids"], step_id)
    _refresh_current_step_pointer(conn, instance_id, version_id)
    return result


def reject_step(
    conn: duckdb.DuckDBPyConnection,
    instance_id: int,
    step_id: int,
    note: str,
    actor: str | None = None,
) -> dict:
    """Send the work back one stage, with a mandatory explanation.

    `note` is required, not optional: a rejection the previous person can't
    act on is worse than none, and this text is what fpna.notify puts in
    their Telegram message (see format_step_message's دلیل بازگشت line).

    Only the previous stage is reset to pending, and only this step is
    marked rejected - the rejecting branch's siblings keep whatever they had
    already approved (the user's explicit call: "فقط همان شخص برمی‌گردد،
    بقیه ادامه می‌دهند"). Rejecting from the first stage is refused: there
    is nobody behind it to send the work back to.
    """
    note = (note or "").strip()
    if not note:
        return {"ok": False, "reason": "برای عدم تایید، نوشتن توضیحات الزامی است.", "returned_to": []}

    version_id = _version_id_of_instance(conn, instance_id)
    if version_id is None:
        return {"ok": False, "reason": "نمونه یافت نشد.", "returned_to": []}

    before = instance_progress(conn, instance_id, version_id)
    if step_id not in before["actionable_ids"]:
        return {"ok": False, "reason": "این مرحله در حال حاضر قابل عدم تایید نیست.", "returned_to": []}

    stage_index = next(
        (s["stage_index"] for stage in before["stages"] for s in stage if s["step_id"] == step_id),
        None,
    )
    if stage_index is None or stage_index == 0:
        return {
            "ok": False,
            "reason": "این اولین مرحله‌ی فرایند است و مرحله‌ی قبلی برای بازگشت ندارد.",
            "returned_to": [],
        }

    previous_stage = before["stages"][stage_index - 1]
    _set_step_state(conn, instance_id, step_id, STATE_REJECTED, note=note, actor=actor)
    for previous_step in previous_stage:
        _set_step_state(conn, instance_id, previous_step["step_id"], STATE_PENDING, note=note, actor=actor)
        _log_history(conn, instance_id, step_id, previous_step["step_id"], "reject", note=note, actor=actor)

    _refresh_current_step_pointer(conn, instance_id, version_id)
    return {
        "ok": True,
        "reason": None,
        "note": note,
        "returned_to": [dict(s) for s in previous_stage],
        "progress": instance_progress(conn, instance_id, version_id),
    }


def start_workflow(conn: duckdb.DuckDBPyConnection, version_id: int) -> dict:
    """Kick a workflow off from the beginning: every step back to pending,
    so the first stage becomes actionable again. Used by the manual "start
    now" button and by run_due_schedules.

    Returns the same shape as approve_step so callers notify the same way -
    `newly_actionable` is the first stage, i.e. exactly whose desk the work
    just landed on.
    """
    instance = get_or_create_instance(conn, version_id)
    instance_id = instance["instance_id"]
    conn.execute(
        """
        UPDATE workflow_instance_step_state
        SET state = ?, note = NULL, actor = NULL, updated_at = current_timestamp
        WHERE instance_id = ?
        """,
        [STATE_PENDING, instance_id],
    )
    _refresh_current_step_pointer(conn, instance_id, version_id)
    progress = instance_progress(conn, instance_id, version_id)
    first_stage = progress["stages"][0] if progress["stages"] else []
    for step in first_stage:
        _log_history(conn, instance_id, None, step["step_id"], "advance")
    return {
        "ok": True,
        "reason": None,
        "instance_id": instance_id,
        "newly_actionable": first_stage,
        "is_complete": progress["is_complete"],
        "progress": progress,
    }


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
    conn.execute("DELETE FROM workflow_instance_step_state WHERE instance_id = ?", [instance_id])
    conn.execute("DELETE FROM workflow_instance WHERE instance_id = ?", [instance_id])


# ---- Scheduled kick-offs ----


def create_schedule(conn: duckdb.DuckDBPyConnection, version_id: int, run_at: datetime) -> int:
    return conn.execute(
        "INSERT INTO workflow_schedule (version_id, run_at) VALUES (?, ?) RETURNING schedule_id",
        [version_id, run_at],
    ).fetchone()[0]


def list_schedules(conn: duckdb.DuckDBPyConnection, version_id: int | None = None) -> list[dict]:
    query = """
        SELECT sc.schedule_id, sc.version_id, v.name, sc.run_at,
               COALESCE(sc.enabled, true), sc.last_run_at, sc.created_at
        FROM workflow_schedule sc
        JOIN workflow_version v ON v.version_id = sc.version_id
    """
    params: list = []
    if version_id is not None:
        query += " WHERE sc.version_id = ?"
        params.append(version_id)
    query += " ORDER BY sc.run_at"
    return [
        {
            "schedule_id": r[0],
            "version_id": r[1],
            "version_name": r[2],
            "run_at": r[3],
            "enabled": bool(r[4]),
            "last_run_at": r[5],
            "created_at": r[6],
        }
        for r in conn.execute(query, params).fetchall()
    ]


def set_schedule_enabled(conn: duckdb.DuckDBPyConnection, schedule_id: int, enabled: bool) -> None:
    conn.execute("UPDATE workflow_schedule SET enabled = ? WHERE schedule_id = ?", [enabled, schedule_id])


def delete_schedule(conn: duckdb.DuckDBPyConnection, schedule_id: int) -> None:
    conn.execute("DELETE FROM workflow_schedule WHERE schedule_id = ?", [schedule_id])


def due_schedules(conn: duckdb.DuckDBPyConnection, now: datetime | None = None) -> list[dict]:
    """Enabled schedules whose run_at has passed and that haven't fired yet.

    "Haven't fired yet" is last_run_at IS NULL OR last_run_at < run_at, not
    a simple "did we run today" - that's what makes a missed schedule fire
    once on the next dashboard open (catch-up) while making it impossible
    for one to fire twice, however often the tick checks.
    """
    now = now or datetime.now()
    return [
        {
            "schedule_id": r[0],
            "version_id": r[1],
            "version_name": r[2],
            "run_at": r[3],
        }
        for r in conn.execute(
            """
            SELECT sc.schedule_id, sc.version_id, v.name, sc.run_at
            FROM workflow_schedule sc
            JOIN workflow_version v ON v.version_id = sc.version_id
            WHERE COALESCE(sc.enabled, true)
              AND sc.run_at <= ?
              AND (sc.last_run_at IS NULL OR sc.last_run_at < sc.run_at)
            ORDER BY sc.run_at
            """,
            [now],
        ).fetchall()
    ]


def mark_schedule_run(conn: duckdb.DuckDBPyConnection, schedule_id: int, when: datetime | None = None) -> None:
    conn.execute(
        "UPDATE workflow_schedule SET last_run_at = ? WHERE schedule_id = ?",
        [when or datetime.now(), schedule_id],
    )


def step_status_summary(conn: duckdb.DuckDBPyConnection, version_id: int) -> list[dict]:
    """Per-step instance counts for one version - drives the pending-work
    summary panel: how many running instances are sitting at each step
    right now, who (if anyone) is assigned to that role, and how many of
    those are overdue against the step's own sla_days. This is deliberately
    scoped to one version rather than "all instances everywhere," matching
    every other view in this app (see _load_view).

    Counts come from workflow_instance_step_state, not from the old
    current_step_id pointer: with parallel stages several steps are legit-
    imately "waiting on someone" at the same moment, which a single pointer
    could never show. A step counts as pending only when it is genuinely
    actionable (its stage's turn has come and it isn't approved yet) - a
    step further down the workflow that simply hasn't been reached is not
    work anybody is sitting on, so it doesn't inflate the count. Overdue is
    measured from that step's own state timestamp, i.e. how long this
    person has had it, not how long the whole instance has been running.
    """
    progress_by_step: dict = {}
    for row in conn.execute(
        "SELECT instance_id FROM workflow_instance WHERE version_id = ?", [version_id]
    ).fetchall():
        progress = instance_progress(conn, row[0], version_id)
        for stage in progress["stages"]:
            for step in stage:
                if step["is_actionable"]:
                    progress_by_step.setdefault(step["step_id"], []).append(step)

    rows = conn.execute(
        """
        SELECT s.step_id, s.step_order, COALESCE(s.label, r.role_name) AS label,
               r.color_hex, r.assignee_name, r.assignee_email, s.sla_days
        FROM workflow_step s
        JOIN dim_role r ON r.role_id = s.role_id
        WHERE s.version_id = ?
        ORDER BY s.step_order, COALESCE(s.lane, 0), s.step_id
        """,
        [version_id],
    ).fetchall()

    summary = []
    for r in rows:
        step_id, stage, label, color_hex, assignee_name, assignee_email, sla_days = r
        waiting = progress_by_step.get(step_id, [])
        overdue = 0
        if sla_days:
            for step in waiting:
                updated_at = step.get("state_updated_at")
                if updated_at and (datetime.now() - updated_at).days > sla_days:
                    overdue += 1
        summary.append(
            {
                "step_id": step_id,
                "step_order": stage,
                "stage": stage,
                "label": label,
                "color_hex": color_hex,
                "assignee_name": assignee_name,
                "assignee_email": assignee_email,
                "sla_days": sla_days,
                "pending_count": len(waiting),
                "overdue_count": overdue,
            }
        )
    return summary


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
                # Carrying stage/lane is what makes a parallel design survive
                # an export/import round trip - without them every branch
                # would come back as its own sequential stage.
                "stage": s["stage"],
                "lane": s["lane"],
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
    # A file exported before parallel stages existed has no "stage" key at
    # all - falling back to a running counter reproduces exactly the old
    # one-step-per-stage linear shape, so old exports still import cleanly.
    stage_numbers: dict = {}
    for step in payload.get("steps", []):
        role = roles_by_name.get(step.get("role_name"))
        if role is None:
            skipped_roles.append(step.get("role_name"))
            continue
        raw_stage = step.get("stage")
        if raw_stage is None:
            raw_stage = order
        if raw_stage not in stage_numbers:
            stage_numbers[raw_stage] = len(stage_numbers)
        step_id = conn.execute(
            "INSERT INTO workflow_step (version_id, role_id, step_order, lane, label) VALUES (?, ?, ?, ?, ?) RETURNING step_id",
            [
                version_id,
                role["role_id"],
                stage_numbers[raw_stage],
                step.get("lane") or 0,
                step.get("label") or None,
            ],
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

"""Parallel stages, the approve/reject rules on top of them, and scheduling.

The shape under test throughout is the one the user asked for: a stage that
fans out to several people at once and only lets the workflow move on once
all of them have signed off, with a rejection sending the work back exactly
one stage and leaving the rejecting branch's siblings untouched.
"""

from datetime import datetime, timedelta

import duckdb
import pytest

from fpna import config, db, workflow


@pytest.fixture
def conn():
    connection = duckdb.connect(":memory:")
    db.run_sql_file(connection, config.SQL_DIR / "schema.sql")
    yield connection
    connection.close()


@pytest.fixture
def roles(conn):
    return {
        "prep": workflow.create_role(conn, "PREP", "Preparer", "#0891b2"),
        "a": workflow.create_role(conn, "A", "Dept A", "#8b5cf6"),
        "b": workflow.create_role(conn, "B", "Dept B", "#ec4899"),
        "ctrl": workflow.create_role(conn, "CTRL", "Controller", "#0f766e"),
    }


@pytest.fixture
def fan_out(conn, roles):
    """Preparer -> (Dept A || Dept B) -> Controller, with one instance."""
    version_id = workflow.create_version(conn, "Parallel")
    workflow.save_steps(
        conn,
        version_id,
        [
            {"role_id": roles["prep"], "label": None, "stage": 0, "lane": 0},
            {"role_id": roles["a"], "label": None, "stage": 1, "lane": 0},
            {"role_id": roles["b"], "label": None, "stage": 1, "lane": 1},
            {"role_id": roles["ctrl"], "label": None, "stage": 2, "lane": 0},
        ],
    )
    instance = workflow.get_or_create_instance(conn, version_id)
    version = workflow.get_version(conn, version_id)
    return {
        "version_id": version_id,
        "instance_id": instance["instance_id"],
        "ids": {s["label"]: s["step_id"] for s in version["steps"]},
    }


def actionable_labels(conn, fan_out):
    progress = workflow.instance_progress(conn, fan_out["instance_id"], fan_out["version_id"])
    return sorted(s["label"] for stage in progress["stages"] for s in stage if s["is_actionable"])


def test_steps_sharing_a_stage_group_into_one_column(conn, fan_out):
    version = workflow.get_version(conn, fan_out["version_id"])
    assert [[s["label"] for s in stage] for stage in version["stages"]] == [
        ["Preparer"],
        ["Dept A", "Dept B"],
        ["Controller"],
    ]


def test_only_first_stage_is_actionable_at_the_start(conn, fan_out):
    assert actionable_labels(conn, fan_out) == ["Preparer"]


def test_completing_a_stage_opens_every_branch_of_the_next_at_once(conn, fan_out):
    result = workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    assert sorted(s["label"] for s in result["newly_actionable"]) == ["Dept A", "Dept B"]
    assert actionable_labels(conn, fan_out) == ["Dept A", "Dept B"]


def test_partial_approval_of_a_parallel_stage_opens_nothing(conn, fan_out):
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    result = workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Dept A"])
    # The aggregation rule: Dept A signing off alone must not release the
    # Controller - the stage isn't done until Dept B signs off too.
    assert result["newly_actionable"] == []
    assert actionable_labels(conn, fan_out) == ["Dept B"]


def test_last_branch_of_a_stage_releases_the_next_stage(conn, fan_out):
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Dept A"])
    result = workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Dept B"])
    assert [s["label"] for s in result["newly_actionable"]] == ["Controller"]


def test_reject_returns_one_stage_and_leaves_siblings_approved(conn, fan_out):
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Dept A"])

    result = workflow.reject_step(
        conn, fan_out["instance_id"], fan_out["ids"]["Dept B"], note="ارقام اشتباه است"
    )
    assert result["ok"] is True
    assert [s["label"] for s in result["returned_to"]] == ["Preparer"]

    states = workflow.instance_step_states(conn, fan_out["instance_id"])
    assert states[fan_out["ids"]["Preparer"]]["state"] == workflow.STATE_PENDING
    assert states[fan_out["ids"]["Dept B"]]["state"] == workflow.STATE_REJECTED
    # The user's explicit call: only the rejecting branch goes back.
    assert states[fan_out["ids"]["Dept A"]]["state"] == workflow.STATE_APPROVED
    assert actionable_labels(conn, fan_out) == ["Preparer"]


def test_reapproving_after_a_reject_reopens_only_the_rejecting_branch(conn, fan_out):
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Dept A"])
    workflow.reject_step(conn, fan_out["instance_id"], fan_out["ids"]["Dept B"], note="اصلاح شود")

    result = workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    assert [s["label"] for s in result["newly_actionable"]] == ["Dept B"]


def test_reject_stores_the_note_for_the_notification(conn, fan_out):
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    workflow.reject_step(conn, fan_out["instance_id"], fan_out["ids"]["Dept A"], note="مبلغ نادرست")

    states = workflow.instance_step_states(conn, fan_out["instance_id"])
    assert states[fan_out["ids"]["Preparer"]]["note"] == "مبلغ نادرست"


def test_reject_requires_a_note(conn, fan_out):
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    result = workflow.reject_step(conn, fan_out["instance_id"], fan_out["ids"]["Dept A"], note="   ")
    assert result["ok"] is False
    assert "توضیحات" in result["reason"]


def test_reject_from_the_first_stage_is_refused(conn, fan_out):
    result = workflow.reject_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"], note="x")
    assert result["ok"] is False


def test_cannot_approve_a_step_whose_turn_has_not_come(conn, fan_out):
    result = workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Controller"])
    assert result["ok"] is False
    assert actionable_labels(conn, fan_out) == ["Preparer"]


def test_workflow_reports_complete_only_after_the_last_stage(conn, fan_out):
    for label in ["Preparer", "Dept A", "Dept B"]:
        workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"][label])
    progress = workflow.instance_progress(conn, fan_out["instance_id"], fan_out["version_id"])
    assert progress["is_complete"] is False

    result = workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Controller"])
    assert result["is_complete"] is True


def test_status_summary_counts_every_open_branch_of_a_parallel_stage(conn, fan_out):
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    pending = {s["label"]: s["pending_count"] for s in workflow.step_status_summary(conn, fan_out["version_id"])}
    # A single current_step_id pointer could only ever have shown one of these.
    assert pending["Dept A"] == 1
    assert pending["Dept B"] == 1
    assert pending["Controller"] == 0


def test_start_workflow_resets_everything_and_opens_the_first_stage(conn, fan_out):
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Preparer"])
    workflow.approve_step(conn, fan_out["instance_id"], fan_out["ids"]["Dept A"])

    result = workflow.start_workflow(conn, fan_out["version_id"])
    assert [s["label"] for s in result["newly_actionable"]] == ["Preparer"]
    assert actionable_labels(conn, fan_out) == ["Preparer"]
    states = workflow.instance_step_states(conn, fan_out["instance_id"])
    assert all(s["state"] == workflow.STATE_PENDING for s in states.values())


def test_editing_steps_preserves_progress_on_surviving_steps(conn, roles):
    version_id = workflow.create_version(conn, "v1")
    workflow.save_steps(
        conn,
        version_id,
        [
            {"role_id": roles["prep"], "label": None, "stage": 0, "key": "new_1"},
            {"role_id": roles["a"], "label": None, "stage": 1, "key": "new_2"},
        ],
    )
    instance = workflow.get_or_create_instance(conn, version_id)
    version = workflow.get_version(conn, version_id)
    prep_step_id = version["steps"][0]["step_id"]
    a_step_id = version["steps"][1]["step_id"]
    workflow.approve_step(conn, instance["instance_id"], prep_step_id)

    # Re-save carrying the existing keys, adding a parallel branch to stage 1.
    workflow.save_steps(
        conn,
        version_id,
        [
            {"role_id": roles["prep"], "label": None, "stage": 0, "key": f"s{prep_step_id}"},
            {"role_id": roles["a"], "label": None, "stage": 1, "lane": 0, "key": f"s{a_step_id}"},
            {"role_id": roles["b"], "label": None, "stage": 1, "lane": 1, "key": "new_3"},
        ],
    )

    states = workflow.instance_step_states(conn, instance["instance_id"])
    assert states[prep_step_id]["state"] == workflow.STATE_APPROVED
    progress = workflow.instance_progress(conn, instance["instance_id"], version_id)
    assert sorted(s["label"] for stage in progress["stages"] for s in stage if s["is_actionable"]) == [
        "Dept A",
        "Dept B",
    ]


def test_save_steps_drops_state_rows_for_deleted_steps(conn, roles):
    version_id = workflow.create_version(conn, "v1")
    workflow.save_steps(conn, version_id, [{"role_id": roles["prep"], "label": None, "stage": 0}])
    instance = workflow.get_or_create_instance(conn, version_id)
    workflow.save_steps(conn, version_id, [{"role_id": roles["a"], "label": None, "stage": 0}])

    remaining = {s["step_id"] for s in workflow.get_version(conn, version_id)["steps"]}
    states = workflow.instance_step_states(conn, instance["instance_id"])
    assert set(states) == remaining


def test_linear_designs_still_work_without_explicit_stages(conn, roles):
    """A step list with no `stage` key at all - what the old canvas sent -
    must still produce one step per stage, i.e. a plain linear workflow."""
    version_id = workflow.create_version(conn, "linear")
    workflow.save_steps(
        conn,
        version_id,
        [{"role_id": roles["prep"], "label": None}, {"role_id": roles["ctrl"], "label": None}],
    )
    version = workflow.get_version(conn, version_id)
    assert [len(stage) for stage in version["stages"]] == [1, 1]


def test_export_import_round_trips_a_parallel_design(conn, fan_out):
    payload = workflow.export_version_json(conn, fan_out["version_id"])
    import json

    new_version_id, skipped = workflow.import_version_json(conn, json.loads(payload), name_override="copy")
    assert skipped == []
    imported = workflow.get_version(conn, new_version_id)
    assert [[s["label"] for s in stage] for stage in imported["stages"]] == [
        ["Preparer"],
        ["Dept A", "Dept B"],
        ["Controller"],
    ]


# ---- Scheduling ----


def test_due_schedules_returns_only_past_and_unfired(conn, fan_out):
    past = workflow.create_schedule(conn, fan_out["version_id"], datetime.now() - timedelta(hours=1))
    workflow.create_schedule(conn, fan_out["version_id"], datetime.now() + timedelta(days=1))

    due = workflow.due_schedules(conn)
    assert [d["schedule_id"] for d in due] == [past]


def test_marking_a_schedule_run_stops_it_firing_again(conn, fan_out):
    schedule_id = workflow.create_schedule(conn, fan_out["version_id"], datetime.now() - timedelta(hours=1))
    workflow.mark_schedule_run(conn, schedule_id)
    assert workflow.due_schedules(conn) == []


def test_disabled_schedules_never_come_due(conn, fan_out):
    schedule_id = workflow.create_schedule(conn, fan_out["version_id"], datetime.now() - timedelta(hours=1))
    workflow.set_schedule_enabled(conn, schedule_id, False)
    assert workflow.due_schedules(conn) == []


def test_delete_schedule(conn, fan_out):
    schedule_id = workflow.create_schedule(conn, fan_out["version_id"], datetime.now())
    workflow.delete_schedule(conn, schedule_id)
    assert workflow.list_schedules(conn, fan_out["version_id"]) == []

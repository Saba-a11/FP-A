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
        "preparer": workflow.create_role(conn, "PREPARER", "Preparer", "#0891b2"),
        "reviewer": workflow.create_role(conn, "REVIEWER", "Finance Reviewer", "#ec4899"),
        "cfo": workflow.create_role(conn, "CFO", "CFO", "#0f766e"),
    }


def test_create_version_starts_as_empty_draft(conn):
    version_id = workflow.create_version(conn, "FY2027 Budget Approval")
    version = workflow.get_version(conn, version_id)
    assert version["name"] == "FY2027 Budget Approval"
    assert version["status"] == "draft"
    assert version["steps"] == []


def test_save_steps_persists_order_and_labels(conn, roles):
    version_id = workflow.create_version(conn, "v1")
    workflow.save_steps(
        conn,
        version_id,
        [
            {"role_id": roles["preparer"], "label": None},
            {"role_id": roles["reviewer"], "label": "Regional Finance Review"},
            {"role_id": roles["cfo"], "label": None},
        ],
    )
    version = workflow.get_version(conn, version_id)
    labels = [s["label"] for s in version["steps"]]
    role_ids = [s["role_id"] for s in version["steps"]]
    assert labels == ["Preparer", "Regional Finance Review", "CFO"]
    assert role_ids == [roles["preparer"], roles["reviewer"], roles["cfo"]]
    assert [s["step_order"] for s in version["steps"]] == [0, 1, 2]


def test_save_steps_fully_replaces_previous_list(conn, roles):
    version_id = workflow.create_version(conn, "v1")
    workflow.save_steps(conn, version_id, [{"role_id": roles["preparer"], "label": None}])
    workflow.save_steps(
        conn,
        version_id,
        [{"role_id": roles["cfo"], "label": None}, {"role_id": roles["reviewer"], "label": None}],
    )
    version = workflow.get_version(conn, version_id)
    assert [s["role_name"] for s in version["steps"]] == ["CFO", "Finance Reviewer"]


def test_activate_version_deactivates_others(conn):
    v1 = workflow.create_version(conn, "v1")
    v2 = workflow.create_version(conn, "v2")
    workflow.activate_version(conn, v1)
    assert workflow.get_version(conn, v1)["status"] == "active"
    assert workflow.get_version(conn, v2)["status"] == "draft"

    workflow.activate_version(conn, v2)
    assert workflow.get_version(conn, v1)["status"] == "draft"
    assert workflow.get_version(conn, v2)["status"] == "active"


def test_create_instance_defaults_to_first_step(conn, roles):
    version_id = workflow.create_version(conn, "v1")
    workflow.save_steps(
        conn,
        version_id,
        [{"role_id": roles["preparer"], "label": None}, {"role_id": roles["cfo"], "label": None}],
    )
    instance_id = workflow.create_instance(conn, version_id, "FY2027 Annual Budget")
    instances = workflow.list_instances(conn, version_id)
    assert len(instances) == 1
    version = workflow.get_version(conn, version_id)
    assert instances[0]["current_step_id"] == version["steps"][0]["step_id"]
    assert instances[0]["instance_id"] == instance_id


def test_create_instance_on_empty_version_has_no_current_step(conn):
    version_id = workflow.create_version(conn, "v1")
    workflow.create_instance(conn, version_id, "Empty cycle")
    instances = workflow.list_instances(conn, version_id)
    assert instances[0]["current_step_id"] is None


def test_set_current_step(conn, roles):
    version_id = workflow.create_version(conn, "v1")
    workflow.save_steps(
        conn,
        version_id,
        [{"role_id": roles["preparer"], "label": None}, {"role_id": roles["cfo"], "label": None}],
    )
    version = workflow.get_version(conn, version_id)
    second_step_id = version["steps"][1]["step_id"]

    instance_id = workflow.create_instance(conn, version_id, "Cycle A")
    workflow.set_current_step(conn, instance_id, second_step_id)

    instance = workflow.list_instances(conn, version_id)[0]
    assert instance["current_step_id"] == second_step_id


def test_save_steps_resets_dangling_instance_pointers(conn, roles):
    """The critical case: save_steps deletes and reinserts every step_id for
    a version, so any instance pointing at an old step_id must not end up
    referencing a row that no longer exists - it should fall back to
    whatever the new first step is instead of dangling."""
    version_id = workflow.create_version(conn, "v1")
    workflow.save_steps(
        conn,
        version_id,
        [{"role_id": roles["preparer"], "label": None}, {"role_id": roles["cfo"], "label": None}],
    )
    old_version = workflow.get_version(conn, version_id)
    old_second_step_id = old_version["steps"][1]["step_id"]

    instance_id = workflow.create_instance(conn, version_id, "Cycle A")
    workflow.set_current_step(conn, instance_id, old_second_step_id)

    # Redesign the template entirely - every step_id changes underneath it.
    workflow.save_steps(
        conn,
        version_id,
        [{"role_id": roles["reviewer"], "label": None}, {"role_id": roles["cfo"], "label": None}],
    )

    new_version = workflow.get_version(conn, version_id)
    new_first_step_id = new_version["steps"][0]["step_id"]
    instance = workflow.list_instances(conn, version_id)[0]
    assert instance["current_step_id"] == new_first_step_id
    # And the old step_id is genuinely gone, not just superseded.
    remaining_ids = {s["step_id"] for s in new_version["steps"]}
    assert old_second_step_id not in remaining_ids


def test_save_steps_leaves_unaffected_instance_alone(conn, roles):
    """An instance already sitting on a step that survives the save
    (same step_id) should not have its progress reset."""
    version_id = workflow.create_version(conn, "v1")
    workflow.save_steps(conn, version_id, [{"role_id": roles["preparer"], "label": None}])
    instance_id = workflow.create_instance(conn, version_id, "Cycle A")
    version = workflow.get_version(conn, version_id)
    step_id = version["steps"][0]["step_id"]
    assert workflow.list_instances(conn, version_id)[0]["current_step_id"] == step_id

    # Re-saving the *identical* single-step list still replaces the row
    # (new step_id) - this documents that even a no-op edit resets progress,
    # which is the deliberate tradeoff, not a bug.
    workflow.save_steps(conn, version_id, [{"role_id": roles["preparer"], "label": None}])
    new_version = workflow.get_version(conn, version_id)
    new_step_id = new_version["steps"][0]["step_id"]
    assert new_step_id != step_id
    assert workflow.list_instances(conn, version_id)[0]["current_step_id"] == new_step_id


def test_duplicate_role_code_raises(conn):
    workflow.create_role(conn, "CFO", "CFO", "#0f766e")
    with pytest.raises(duckdb.ConstraintException):
        workflow.create_role(conn, "CFO", "Chief Financial Officer", "#123456")


def test_list_versions_reports_step_count(conn, roles):
    v1 = workflow.create_version(conn, "v1")
    workflow.save_steps(
        conn,
        v1,
        [{"role_id": roles["preparer"], "label": None}, {"role_id": roles["cfo"], "label": None}],
    )
    versions = {v["version_id"]: v for v in workflow.list_versions(conn)}
    assert versions[v1]["step_count"] == 2

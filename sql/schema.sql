-- FP-A: Budgeting Workflow Designer schema.
--
-- Two layers, on purpose:
--   workflow_version + workflow_step   = the editable TEMPLATE (the sequence
--                                        of role-based steps you drag-and-drop
--                                        to design), versioned.
--   workflow_instance                  = one actual running "case" of a
--                                        template, tracking which step it is
--                                        currently sitting at.
-- This mirrors how a real approval workflow works: you design the process
-- once (and can redesign it later without losing history), then run many
-- instances of it (e.g. one per fiscal year) each progressing independently.

CREATE SEQUENCE IF NOT EXISTS seq_role_id START 1;
CREATE TABLE IF NOT EXISTS dim_role (
    role_id INTEGER PRIMARY KEY DEFAULT nextval('seq_role_id'),
    role_code VARCHAR UNIQUE NOT NULL,
    role_name VARCHAR NOT NULL,
    color_hex VARCHAR NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS seq_workflow_version_id START 1;
CREATE TABLE IF NOT EXISTS workflow_version (
    version_id INTEGER PRIMARY KEY DEFAULT nextval('seq_workflow_version_id'),
    name VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'draft',  -- 'draft' | 'active'
    created_by VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE SEQUENCE IF NOT EXISTS seq_workflow_step_id START 1;
CREATE TABLE IF NOT EXISTS workflow_step (
    step_id INTEGER PRIMARY KEY DEFAULT nextval('seq_workflow_step_id'),
    version_id INTEGER NOT NULL REFERENCES workflow_version(version_id),
    role_id INTEGER NOT NULL REFERENCES dim_role(role_id),
    step_order INTEGER NOT NULL,
    label VARCHAR  -- optional override, falls back to the role's name if null
);

-- current_step_id is deliberately NOT a real FOREIGN KEY, unlike version_id
-- above: save_steps() always deletes every workflow_step row for a version
-- and reinserts a fresh set (simplest correct way to persist a
-- drag-and-drop reorder/add/remove), so a hard FK here would reject that
-- DELETE the moment any instance still pointed at an old step_id. Validity
-- is instead maintained in Python (workflow.save_steps resets any instance
-- whose current_step_id no longer exists back to the new first step) - the
-- same "validated in code, not the schema" tradeoff XP-A documents for its
-- own polymorphic version_id column.
CREATE SEQUENCE IF NOT EXISTS seq_workflow_instance_id START 1;
CREATE TABLE IF NOT EXISTS workflow_instance (
    instance_id INTEGER PRIMARY KEY DEFAULT nextval('seq_workflow_instance_id'),
    version_id INTEGER NOT NULL REFERENCES workflow_version(version_id),
    name VARCHAR NOT NULL,
    current_step_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

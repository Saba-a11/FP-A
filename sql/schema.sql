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

-- Per-step operating detail, added after the fact via ALTER so upgrading an
-- already-seeded database is as simple as re-running this file (every
-- statement here is IF NOT EXISTS/idempotent, same principle as the
-- CREATE TABLE IF NOT EXISTS calls above). All nullable: a step works fine
-- with none of this filled in, same as label - see workflow.save_steps
-- (which upserts by the step's stable id specifically so this survives a
-- Save) and dashboard's step-details editor.
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS owner VARCHAR;  -- مالک
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS duty VARCHAR;  -- وظیفه
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS input_desc VARCHAR;  -- ورودی
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS output_desc VARCHAR;  -- خروجی
-- acceptance_criteria replaced the older `eligibility` column: this app
-- needed "what makes a submitted output acceptable to the next person"
-- (شرایط پذیرش خروجی), not "who's qualified to hold the role" (شرایط احراز)
-- - see seed.migrate_eligibility_to_acceptance_criteria for the one-time
-- upgrade path that copies any old data over and drops the old column.
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS acceptance_criteria VARCHAR;  -- شرایط پذیرش خروجی
-- template_path is relative to PROJECT_ROOT (see config.TEMPLATES_DIR),
-- never an absolute path - so the database stays portable across machines.
-- template_original_name is what the user actually uploaded, kept separate
-- from the on-disk filename so downloads offer a sensible name even though
-- the file itself is stored as step_<id>/<sanitized-name> to avoid clashes.
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS template_path VARCHAR;
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS template_original_name VARCHAR;
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS sla_days INTEGER;  -- null = no deadline tracked
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS is_optional BOOLEAN DEFAULT false;  -- nullable, not NOT NULL: DuckDB's ALTER ADD COLUMN can't carry a NOT NULL constraint - treat NULL as false in code, same as is_optional's own default
-- Per-step override for the subject line of the Telegram notification sent
-- when an instance lands on this step (see fpna.notify) - null falls back
-- to an auto-generated subject, same "override with a fallback" shape as
-- workflow_step.label falling back to the role's name.
ALTER TABLE workflow_step ADD COLUMN IF NOT EXISTS notification_subject VARCHAR;  -- موضوع پیام اعلان

-- Who actually holds a role, for the pending-work summary and (later) real
-- notifications - both optional, since day-to-day use of the canvas/roles
-- never required a real person behind a role before this.
ALTER TABLE dim_role ADD COLUMN IF NOT EXISTS assignee_name VARCHAR;
ALTER TABLE dim_role ADD COLUMN IF NOT EXISTS assignee_email VARCHAR;

-- current_step_id is deliberately NOT a real FOREIGN KEY, unlike version_id
-- above: save_steps() can still delete a workflow_step row (one dropped
-- from the canvas), so a hard FK here would reject that DELETE the moment
-- any instance still pointed at the removed step_id. Validity is instead
-- maintained in Python (workflow.save_steps resets any instance whose
-- current_step_id no longer exists back to the new first step) - the same
-- "validated in code, not the schema" tradeoff XP-A documents for its own
-- polymorphic version_id column.
CREATE SEQUENCE IF NOT EXISTS seq_workflow_instance_id START 1;
CREATE TABLE IF NOT EXISTS workflow_instance (
    instance_id INTEGER PRIMARY KEY DEFAULT nextval('seq_workflow_instance_id'),
    version_id INTEGER NOT NULL REFERENCES workflow_version(version_id),
    name VARCHAR NOT NULL,
    current_step_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- One row per step transition - the audit trail. Written automatically by
-- workflow.set_current_step (every click that changes an instance's
-- current step logs itself, no extra step required), and can carry an
-- optional note. There's no login system in this app, so `actor` is
-- free-text the user can optionally type, not an authenticated identity.
CREATE SEQUENCE IF NOT EXISTS seq_workflow_instance_history_id START 1;
CREATE TABLE IF NOT EXISTS workflow_instance_history (
    history_id INTEGER PRIMARY KEY DEFAULT nextval('seq_workflow_instance_history_id'),
    instance_id INTEGER NOT NULL REFERENCES workflow_instance(instance_id),
    from_step_id INTEGER,
    to_step_id INTEGER NOT NULL,
    action VARCHAR NOT NULL,  -- 'advance' | 'reject' | 'skip'
    note VARCHAR,
    actor VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

"""Dash callback wiring for the FP-A Budgeting Workflow Designer.

The drag-and-drop canvas itself is owned by client-side JS
(assets/dragdrop.js) - it writes the current step list into
workflow-steps-store via dash_clientside.set_props(). Everything here is
the server-side half: version switching/creation/activation, persisting
the step list on Save, managing roles, instances, step detail/templates,
and the JSON export/import of a version.
"""

import base64
import hashlib
import json
from datetime import datetime

import duckdb
from dash import ALL, Input, Output, State, ctx, dcc, no_update

import layout
from fpna import config, db, notify, workflow

DEFAULT_VERSION_NAME = "گردش‌کار جدید"


def _load_view(conn: duckdb.DuckDBPyConnection, version_id: int | None):
    versions = workflow.list_versions(conn)
    version = workflow.get_version(conn, version_id) if version_id is not None else None
    # Always exactly the version's one run (auto-created on first look) -
    # see workflow.get_or_create_instance.
    instances = [workflow.get_or_create_instance(conn, version_id)] if version_id is not None else []
    summary = workflow.step_status_summary(conn, version_id) if version_id is not None else []
    return versions, version, instances, summary


def _history_by_instance(conn: duckdb.DuckDBPyConnection, instances: list[dict]) -> dict[int, list[dict]]:
    return {i["instance_id"]: workflow.list_instance_history(conn, i["instance_id"]) for i in instances}


def _progress_for(conn: duckdb.DuckDBPyConnection, version_id: int | None) -> dict | None:
    """The instance-progress read model for the selected version, or None if
    nothing is selected. Every place that re-renders the instance list goes
    through this, so no callback ever hand-rolls "whose turn is it".
    """
    if version_id is None:
        return None
    instance = workflow.get_or_create_instance(conn, version_id)
    return workflow.instance_progress(conn, instance["instance_id"], version_id)


def _render_instance_list(
    conn: duckdb.DuckDBPyConnection,
    version_id: int | None,
    expanded_history_instance_id=None,
    editing_instance_id=None,
):
    """Rebuilds the instance-list subtree for the selected version. Six
    different callbacks end with exactly this, so it lives here once rather
    than being copy-pasted with slightly different arguments each time.
    """
    if version_id is None:
        return layout.build_instance_list([], None)
    instances = [workflow.get_or_create_instance(conn, version_id)]
    return layout.build_instance_list(
        instances,
        _progress_for(conn, version_id),
        editing_instance_id=editing_instance_id,
        history_by_instance=_history_by_instance(conn, instances),
        expanded_history_instance_id=expanded_history_instance_id,
    )


def _notify_steps(conn: duckdb.DuckDBPyConnection, instance_id: int, version_id: int, steps: list[dict], event: str, note: str | None = None) -> None:
    """Send one notification per step that just landed on someone's desk.

    Plural on purpose: completing a stage can open several parallel branches
    at once, and each of those people needs their own message with their own
    step's detail and template file attached.
    """
    for step in steps:
        _notify_step_change(conn, instance_id, version_id, step["step_id"], event, note)


def _notify_step_change(
    conn: duckdb.DuckDBPyConnection, instance_id: int, version_id: int, step_id: int, event: str, note: str | None = None
) -> None:
    """Best-effort Telegram notification for one step transition - called
    right after every workflow.set_current_step/skip_current_step call that
    changes an instance's current step, and from save_steps for the one-time
    "this workflow's run now has a real current step" moment. Deliberately
    swallows its own result (see notify.notify_step_change's (ok, error)
    return): per the grill-me session (Q8), a failed send must never break
    the callback that just persisted the transition, and this app has no
    per-instance status/toast Output to route the error into today - it
    only ever reaches notify.send_message's own logger.warning. A future
    pass can thread that error into the UI without touching call sites.
    """
    instance = workflow.get_instance(conn, instance_id)
    step = workflow.get_step(conn, step_id)
    if instance is None or step is None:
        return
    version = workflow.get_version(conn, version_id)
    steps = version["steps"] if version else []
    is_final = bool(steps) and steps[-1]["step_id"] == step_id  # steps come step_order-ordered - see workflow.get_version
    notify.notify_step_change(instance, step, event, note, is_final_step=is_final)


def register_callbacks(app, conn: duckdb.DuckDBPyConnection) -> None:
    @app.callback(
        Output("page-content", "children"),
        Output("module-header", "children"),
        Output({"type": "module-nav-btn", "module": ALL}, "className"),
        Output("active-module", "data"),
        Input({"type": "module-nav-btn", "module": ALL}, "n_clicks"),
        # "Jump to module X" buttons living inside a page - e.g. the
        # designer's "مدیریت نقش‌ها", which hands the user to the settings
        # module where role administration now lives. Routing them through
        # this same callback (rather than a second one that also writes
        # page-content) keeps module switching in exactly one place.
        #
        # Matched with ALL rather than named individually on purpose: such a
        # button exists on one module only, and a plain string Input that
        # vanishes while this callback is still live (its sidebar inputs
        # always exist) is what Dash reports as "a nonexistent object was
        # used in an Input". An ALL matcher may legally match nothing.
        Input({"type": "goto-module-btn", "module": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def switch_module(_clicks, _goto_module_clicks):
        # Same remount-vs-click ambiguity fixed for advance_step below:
        # nothing here re-renders the nav buttons themselves, but Dash
        # still fires this callback once at hydration with every n_clicks
        # already at its initial 0, which must not be mistaken for a real
        # click on module "0"/whichever sorts first.
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update, no_update, no_update

        # Both id shapes carry the destination in "module", so the two cases
        # read the same field - only the "type" differs.
        module_id = triggered["module"]
        classnames = [layout.sidebar_button_class(m["id"], module_id) for m in layout.MODULES]
        header = layout.build_module_header(module_id)

        if module_id == "workflow":
            # Same "pick a version to show" logic as app.serve_layout - re-
            # entering the workflow module always starts from its first
            # version, same as a fresh page load would (no attempt yet to
            # remember which version was showing before you switched away).
            versions = workflow.list_versions(conn)
            if not versions:
                workflow.create_version(conn, DEFAULT_VERSION_NAME)
                versions = workflow.list_versions(conn)
            selected_version_id = versions[0]["version_id"]
            selected_version = workflow.get_version(conn, selected_version_id)
            roles = workflow.list_roles(conn)
            instances = [workflow.get_or_create_instance(conn, selected_version_id)]
            summary = workflow.step_status_summary(conn, selected_version_id)
            content = layout.build_module_content(
                module_id,
                roles,
                versions,
                selected_version,
                instances,
                status_summary=summary,
                history_by_instance=_history_by_instance(conn, instances),
                progress=_progress_for(conn, selected_version_id),
            )
        elif module_id == "settings":
            content = layout.build_module_content(
                module_id,
                workflow.list_roles(conn),
                workflow.list_versions(conn),
                None,
                [],
                schedules=workflow.list_schedules(conn),
            )
        else:
            content = layout.build_module_content(module_id, [], [], None, [])

        return content, header, classnames, module_id

    @app.callback(
        Output("workflow-design-tab", "style"),
        Output("workflow-instances-tab", "style"),
        Output("workflow-tab-design-btn", "className"),
        Output("workflow-tab-instances-btn", "className"),
        Input("workflow-tab-design-btn", "n_clicks"),
        Input("workflow-tab-instances-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def switch_workflow_tab(_design_clicks, _instances_clicks):
        # Both tab bodies always exist in the DOM (see
        # layout.build_designer_page's docstring) - switching tabs is just
        # a style.display flip plus which tab button looks active, never a
        # re-render, so it's instant and can't hit the Dash-validator
        # "nonexistent Input" trap a conditionally-rendered tab would.
        active = "instances" if ctx.triggered_id == "workflow-tab-instances-btn" else "design"
        return (
            layout.workflow_tab_container_style(visible=active == "design"),
            layout.workflow_tab_container_style(visible=active == "instances"),
            layout.workflow_tab_button_class("design", active),
            layout.workflow_tab_button_class("instances", active),
        )

    @app.callback(
        Output("version-bar-container", "children"),
        Output("fpa-steps-payload", "data-steps"),
        Output("fpa-steps-payload", "data-version-id"),
        Output("instance-list", "children", allow_duplicate=True),
        Output("workflow-steps-store", "data"),
        Output("status-summary-content", "children", allow_duplicate=True),
        Output("step-details-list", "children", allow_duplicate=True),
        Output("version-action-status", "children"),
        Output("new-version-name", "value"),
        Input("version-picker", "value"),
        Input("create-version-btn", "n_clicks"),
        State("new-version-name", "value"),
        State("expanded-history-instance-id", "data"),
        prevent_initial_call=True,
    )
    def switch_or_create(selected_version_id, create_clicks, new_name, expanded_history_instance_id):
        triggered = ctx.triggered_id
        status_msg = ""
        reset_name = no_update

        if triggered == "create-version-btn":
            if not create_clicks:
                return (no_update,) * 9
            name = (new_name or "").strip() or DEFAULT_VERSION_NAME
            selected_version_id = workflow.create_version(conn, name)
            status_msg = f"«{name}» به‌عنوان یک پیش‌نویس جدید ایجاد شد."
            reset_name = ""
        # else: triggered == "version-picker" -> plain switch, just re-render below.

        versions, version, instances, summary = _load_view(conn, selected_version_id)
        steps = version["steps"] if version else []
        return (
            layout.build_version_bar(versions, version),
            layout.steps_json(steps),
            layout.canvas_render_token(version),
            _render_instance_list(conn, selected_version_id, expanded_history_instance_id),
            layout.steps_store_payload(steps),
            layout.build_status_summary(summary),
            layout.build_step_details_list(steps),
            status_msg,
            reset_name,
        )

    @app.callback(
        Output("version-picker", "options"),
        Output("version-action-status", "children", allow_duplicate=True),
        Output("last-import-hash", "data"),
        Input("import-version-upload", "contents"),
        State("import-version-upload", "filename"),
        State("last-import-hash", "data"),
        prevent_initial_call=True,
    )
    def import_version(contents, _filename, last_hash):
        # Only ever touches version-picker's *options* (adds the new
        # version to the list), never its *value* or the surrounding
        # version-bar-container - found live: rebuilding the whole
        # container recreates the Dropdown as a new element, which Dash
        # treats as a value change even though the value is numerically
        # identical, which cascades into switch_or_create_or_activate
        # (version-picker.value is its Input) - and that callback, seeing
        # a plain "switch" (not create/activate), always sets
        # version-action-status back to "", silently blanking the message
        # this callback had just set. Leaving version-picker's *value*
        # untouched - only ever adding to *options* - never triggers that
        # cascade in the first place.
        if not contents:
            return no_update, no_update, no_update
        # dcc.Upload's `contents` fires this callback more than once for a
        # *single* real file selection (confirmed live: 3 update-component
        # round-trips, 3 versions imported, from one upload) - contents
        # itself can't be reset to break the repeat because it's this same
        # callback's own Input (Dash rejects an Output on the exact prop a
        # callback also reads as Input). Deduping by content hash against
        # the last one actually processed is what stops the same file
        # being imported 2-3 times over.
        content_hash = hashlib.sha256(contents.encode("utf-8")).hexdigest()
        if content_hash == last_hash:
            return no_update, no_update, no_update
        try:
            _header, b64data = contents.split(",", 1)
            raw = base64.b64decode(b64data).decode("utf-8")
            payload = json.loads(raw)
        except Exception:
            return no_update, "فایل JSON نامعتبر است یا خوانده نشد.", content_hash

        new_version_id, skipped_roles = workflow.import_version_json(conn, payload)
        imported = workflow.get_version(conn, new_version_id)
        msg = f"«{imported['name']}» به‌عنوان یک نسخه‌ی جدید وارد شد — از فهرست نسخه‌ها انتخابش کنید."
        if skipped_roles:
            msg += f" (این نقش‌ها در فایل بودند ولی در این پایگاه‌داده نیستند، پس ردشدند: {', '.join(skipped_roles)})"

        versions = workflow.list_versions(conn)
        return layout.version_options(versions), msg, content_hash

    @app.callback(
        Output("version-export-download", "data"),
        Input("export-version-btn", "n_clicks"),
        State("version-picker", "value"),
        prevent_initial_call=True,
    )
    def export_version(n_clicks, version_id):
        if not n_clicks or version_id is None:
            return no_update
        version = workflow.get_version(conn, version_id)
        if version is None:
            return no_update
        payload_str = workflow.export_version_json(conn, version_id)
        return dcc.send_string(payload_str, filename=f"{version['name']}.json")

    @app.callback(
        Output("fpa-steps-payload", "data-steps", allow_duplicate=True),
        Output("fpa-steps-payload", "data-version-id", allow_duplicate=True),
        Output("instance-list", "children", allow_duplicate=True),
        Output("workflow-steps-store", "data", allow_duplicate=True),
        Output("status-summary-content", "children", allow_duplicate=True),
        Output("step-details-list", "children", allow_duplicate=True),
        Output("save-steps-status", "children"),
        # The dropdown label carries the step count ("... (4 مرحله)"), so a
        # save that changes the number of steps has to refresh it or the
        # title keeps showing the pre-save count until a page reload.
        #
        # Only *options* is rewritten, never the whole version-bar-container:
        # rebuilding that container recreates the Dropdown as a new element,
        # which fires version-picker.value and re-triggers switch_or_create,
        # which would then blank this callback's own status message. Same
        # reasoning (and same fix) as import_version below.
        Output("version-picker", "options", allow_duplicate=True),
        Input("save-steps-btn", "n_clicks"),
        State("version-picker", "value"),
        State("workflow-steps-store", "data"),
        State("expanded-history-instance-id", "data"),
        prevent_initial_call=True,
    )
    def save_steps(n_clicks, version_id, steps_data, expanded_history_instance_id):
        if not n_clicks:
            return (no_update,) * 8
        if version_id is None:
            return (
                no_update, no_update, no_update, no_update, no_update, no_update,
                "اول یک نسخه را انتخاب یا ایجاد کنید.",
                no_update,
            )

        # Which steps were actionable *before* the save, so the ones that
        # become actionable purely because of it (a version that had no steps
        # at all until now, or an edit that opened a new first stage) get the
        # same "it's on your desk" notification any other hand-off would
        # send. Comparing before/after rather than "did it have a current
        # step" is what keeps this correct for a parallel first stage, where
        # several people become actionable at the same moment.
        instance_before = workflow.get_or_create_instance(conn, version_id)
        before_actionable = workflow.instance_progress(
            conn, instance_before["instance_id"], version_id
        )["actionable_ids"]

        workflow.save_steps(conn, version_id, steps_data or [])

        version = workflow.get_version(conn, version_id)
        instance = workflow.get_or_create_instance(conn, version_id)
        after = workflow.instance_progress(conn, instance["instance_id"], version_id)
        newly_actionable = [
            step
            for stage in after["stages"]
            for step in stage
            if step["step_id"] in after["actionable_ids"] - before_actionable
        ]
        _notify_steps(conn, instance["instance_id"], version_id, newly_actionable, "advance")
        summary = workflow.step_status_summary(conn, version_id)
        steps = version["steps"] if version else []
        return (
            layout.steps_json(steps),
            layout.canvas_render_token(version),
            _render_instance_list(conn, version_id, expanded_history_instance_id),
            layout.steps_store_payload(steps),
            layout.build_status_summary(summary),
            layout.build_step_details_list(steps),
            f"ذخیره شد — {len(steps)} مرحله.",
            layout.version_options(workflow.list_versions(conn)),
        )

    @app.callback(
        Output("role-manager", "children", allow_duplicate=True),
        Output("add-role-status", "children"),
        Output("new-role-name", "value"),
        Input("add-role-btn", "n_clicks"),
        State("new-role-name", "value"),
        prevent_initial_call=True,
    )
    def add_role(n_clicks, name):
        if not n_clicks:
            return no_update, no_update, no_update
        name = (name or "").strip()
        if not name:
            return no_update, "نام نقش را وارد کنید.", no_update

        roles = workflow.list_roles(conn)
        color = layout.ROLE_COLOR_CYCLE[len(roles) % len(layout.ROLE_COLOR_CYCLE)]
        code = name.upper().replace(" ", "_")[:40]
        try:
            workflow.create_role(conn, code, name, color)
        except duckdb.ConstraintException:
            return no_update, f"نقشی با نام «{name}» از قبل وجود دارد.", no_update

        roles = workflow.list_roles(conn)
        return layout.build_role_manager(roles), f"«{name}» اضافه شد.", ""

    @app.callback(
        Output("role-manager", "children", allow_duplicate=True),
        Output("editing-role-id", "data"),
        Input({"type": "role-chip-label", "role_id": ALL}, "n_clicks"),
        Input({"type": "role-name-input", "role_id": ALL}, "n_submit"),
        Input({"type": "role-name-save", "role_id": ALL}, "n_clicks"),
        Input({"type": "role-name-cancel", "role_id": ALL}, "n_clicks"),
        State({"type": "role-name-input", "role_id": ALL}, "value"),
        State({"type": "role-assignee-name-input", "role_id": ALL}, "value"),
        State({"type": "role-assignee-email-input", "role_id": ALL}, "value"),
        prevent_initial_call=True,
    )
    def edit_role(_label_clicks, _submits, _save_clicks, _cancel_clicks, name_values, assignee_name_values, assignee_email_values):
        # Same remount-vs-click ambiguity fixed for advance_step below: this
        # callback's own Output (role-manager) contains every id it listens
        # on, so re-rendering the list for *any* reason (e.g. clicking a
        # different role's edit button) makes the whole pattern-matched set
        # look like it just "changed" too. Only trust a genuine trigger with
        # both a real id and a truthy value.
        #
        # No status-summary Output any more: role editing lives in the
        # settings module now, and the summary tiles it used to refresh only
        # exist on the workflow module, which is never mounted at the same
        # time. Those tiles are rebuilt from scratch on the next module
        # switch anyway (switch_module), so an assignee rename still shows up
        # the moment you go back to look at them.
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update

        role_id = triggered["role_id"]
        if triggered["type"] == "role-chip-label":
            editing_role_id = role_id
        elif triggered["type"] == "role-name-cancel":
            editing_role_id = None
        else:  # "role-name-save" click, or Enter (n_submit) in the name field
            new_name = (name_values[0] if name_values else "").strip()
            assignee_name = (assignee_name_values[0] if assignee_name_values else "").strip()
            assignee_email = (assignee_email_values[0] if assignee_email_values else "").strip()
            if new_name:
                workflow.update_role_details(conn, role_id, new_name, assignee_name, assignee_email)
            editing_role_id = None

        roles = workflow.list_roles(conn)
        return layout.build_role_manager(roles, editing_role_id=editing_role_id), editing_role_id

    @app.callback(
        Output("delete-role-confirm", "displayed"),
        Output("delete-role-confirm", "message"),
        Output("pending-delete-role-id", "data"),
        Output("add-role-status", "children", allow_duplicate=True),
        Input({"type": "role-delete-btn", "role_id": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def ask_delete_role(_clicks):
        # Same "ask via native confirm, delete only on submit" shape as
        # ask_delete_instance - a role delete is destructive and, unlike a
        # rename, has no undo.
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update, no_update, no_update

        role_id = triggered["role_id"]
        roles = workflow.list_roles(conn)
        match = next((r for r in roles if r["role_id"] == role_id), None)
        name = match["role_name"] if match else ""
        usage = workflow.role_step_usage_count(conn, role_id)
        if usage:
            # Not actually a yes/no question, so skip the native confirm
            # dialog entirely here (an OK/Cancel pair reads oddly on a
            # notice, not a question) - just report why straight on the
            # page. confirm_delete_role still re-checks usage on its own
            # before ever deleting, so this early message is only ever a
            # convenience, never the sole guard.
            return (
                False,
                no_update,
                None,
                f"«{name}» در {usage} مرحله از گردش‌کارهای موجود استفاده شده و قابل حذف نیست.",
            )
        return True, f"نقش «{name}» حذف شود؟ این کار قابل بازگشت نیست.", role_id, no_update

    @app.callback(
        Output("role-manager", "children", allow_duplicate=True),
        Output("add-role-status", "children", allow_duplicate=True),
        Output("delete-role-confirm", "displayed", allow_duplicate=True),
        Input("delete-role-confirm", "submit_n_clicks"),
        State("pending-delete-role-id", "data"),
        prevent_initial_call=True,
    )
    def confirm_delete_role(_submit_clicks, pending_role_id):
        if not pending_role_id:
            return no_update, no_update, False
        # Re-check usage right before deleting (see ask_delete_role) instead
        # of trusting the count from when the dialog opened.
        if workflow.role_step_usage_count(conn, pending_role_id):
            return no_update, "این نقش دیگر قابل حذف نیست - در یکی از مراحل استفاده شده.", False
        workflow.delete_role(conn, pending_role_id)
        roles = workflow.list_roles(conn)
        return layout.build_role_manager(roles), "نقش حذف شد.", False

    @app.callback(
        Output("instance-list", "children", allow_duplicate=True),
        Output("editing-instance-id", "data"),
        Input({"type": "instance-name-label", "instance_id": ALL}, "n_clicks"),
        Input({"type": "instance-name-input", "instance_id": ALL}, "n_submit"),
        Input({"type": "instance-name-save", "instance_id": ALL}, "n_clicks"),
        Input({"type": "instance-name-cancel", "instance_id": ALL}, "n_clicks"),
        State({"type": "instance-name-input", "instance_id": ALL}, "value"),
        State("version-picker", "value"),
        State("expanded-history-instance-id", "data"),
        prevent_initial_call=True,
    )
    def edit_instance_name(_label_clicks, _submits, _save_clicks, _cancel_clicks, input_values, version_id, expanded_history_instance_id):
        # Same remount-vs-click guard as edit_role - this callback's own
        # Output (instance-list) contains every id it listens on.
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update

        instance_id = triggered["instance_id"]
        if triggered["type"] == "instance-name-label":
            editing_instance_id = instance_id
        elif triggered["type"] == "instance-name-cancel":
            editing_instance_id = None
        else:  # "instance-name-save" click, or Enter (n_submit) inside the input
            new_name = (input_values[0] if input_values else "").strip()
            if new_name:
                workflow.rename_instance(conn, instance_id, new_name)
            editing_instance_id = None

        version = workflow.get_version(conn, version_id) if version_id is not None else None
        instances = [workflow.get_or_create_instance(conn, version_id)] if version_id is not None else []
        steps = version["steps"] if version else []
        return (
            _render_instance_list(
                conn, version_id, expanded_history_instance_id, editing_instance_id=editing_instance_id
            ),
            editing_instance_id,
        )

    @app.callback(
        Output("instance-list", "children", allow_duplicate=True),
        Output("status-summary-content", "children", allow_duplicate=True),
        Input({"type": "approve-step-btn", "instance_id": ALL, "step_id": ALL}, "n_clicks"),
        Input({"type": "skip-step-btn", "instance_id": ALL, "step_id": ALL}, "n_clicks"),
        Input({"type": "restart-instance-btn", "instance_id": ALL}, "n_clicks"),
        State("version-picker", "value"),
        State("expanded-history-instance-id", "data"),
        prevent_initial_call=True,
    )
    def advance_step(_approve_clicks, _skip_clicks, _restart_clicks, version_id, expanded_history_instance_id):
        """The three forward moves - approve, skip an optional step, and
        restart the whole run - share one callback because they share their
        entire tail: apply the move, notify whoever it just landed on, then
        re-render. Only their first line differs.

        triggered_id is None when Dash fires this because the whole set of
        pattern-matched buttons was just replaced (e.g. instance-list
        re-rendered by an unrelated callback), not because one was really
        clicked - the same remount-vs-click ambiguity fixed in XP-A's button
        callbacks. Only a genuine click gives a real id here.
        """
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update

        instance_id = triggered["instance_id"]
        if triggered["type"] == "approve-step-btn":
            result = workflow.approve_step(conn, instance_id, triggered["step_id"])
        elif triggered["type"] == "skip-step-btn":
            result = workflow.skip_step(conn, instance_id, triggered["step_id"])
        else:
            result = workflow.start_workflow(conn, version_id)

        if result["ok"]:
            # One message per branch that just opened - a completed parallel
            # stage can hand work to several people at once.
            _notify_steps(
                conn,
                instance_id,
                version_id,
                result["newly_actionable"],
                "skip" if triggered["type"] == "skip-step-btn" else "advance",
            )

        summary = workflow.step_status_summary(conn, version_id) if version_id is not None else []
        return (
            _render_instance_list(conn, version_id, expanded_history_instance_id),
            layout.build_status_summary(summary),
        )

    @app.callback(
        Output("reject-backdrop", "style"),
        Output("reject-modal-subtitle", "children"),
        Output("reject-note-input", "value"),
        Output("reject-modal-status", "children"),
        Output("pending-reject-step-id", "data"),
        Input({"type": "reject-step-btn", "instance_id": ALL, "step_id": ALL}, "n_clicks"),
        Input("reject-cancel-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_or_close_reject_modal(_reject_clicks, _cancel_clicks):
        """Opens the mandatory-comment box for a rejection, or closes it.

        Deliberately does NOT listen on reject-confirm-btn, for the same
        reason open_or_close_step_detail doesn't listen on its save button:
        the confirm callback needs to read pending-reject-step-id as State,
        and if this one also fired on that click the two would race to
        decide the store's value before the other read it.
        """
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return (no_update,) * 5

        if triggered == "reject-cancel-btn":
            return layout.reject_backdrop_style(hidden=True), no_update, "", "", None

        step = workflow.get_step(conn, triggered["step_id"])
        subtitle = ""
        if step:
            subtitle = f"مرحله‌ی «{step['label']}» به مرحله‌ی قبل بازگردانده می‌شود."
        return layout.reject_backdrop_style(hidden=False), subtitle, "", "", triggered["step_id"]

    @app.callback(
        Output("reject-backdrop", "style", allow_duplicate=True),
        Output("reject-modal-status", "children", allow_duplicate=True),
        Output("pending-reject-step-id", "data", allow_duplicate=True),
        Output("instance-list", "children", allow_duplicate=True),
        Output("status-summary-content", "children", allow_duplicate=True),
        Input("reject-confirm-btn", "n_clicks"),
        State("pending-reject-step-id", "data"),
        State("reject-note-input", "value"),
        State("version-picker", "value"),
        State("expanded-history-instance-id", "data"),
        prevent_initial_call=True,
    )
    def confirm_reject(n_clicks, step_id, note, version_id, expanded_history_instance_id):
        if not n_clicks or step_id is None or version_id is None:
            return (no_update,) * 5

        instance = workflow.get_or_create_instance(conn, version_id)
        result = workflow.reject_step(conn, instance["instance_id"], step_id, note or "")
        if not result["ok"]:
            # Stays open with the reason shown - most often the empty-note
            # case, where closing the box would just lose what they typed.
            return no_update, result["reason"], no_update, no_update, no_update

        # The people the work went *back* to get the rejection note in their
        # message - that text is the whole point of requiring it.
        _notify_steps(
            conn,
            instance["instance_id"],
            version_id,
            result["returned_to"],
            "reject",
            note=result["note"],
        )

        summary = workflow.step_status_summary(conn, version_id)
        return (
            layout.reject_backdrop_style(hidden=True),
            "",
            None,
            _render_instance_list(conn, version_id, expanded_history_instance_id),
            layout.build_status_summary(summary),
        )

    @app.callback(
        Output("instance-list", "children", allow_duplicate=True),
        Input({"type": "instance-note-save-btn", "instance_id": ALL}, "n_clicks"),
        State({"type": "instance-note-input", "instance_id": ALL}, "value"),
        State("version-picker", "value"),
        State("expanded-history-instance-id", "data"),
        prevent_initial_call=True,
    )
    def add_instance_note(_clicks, input_values, version_id, expanded_history_instance_id):
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update
        instance_id = triggered["instance_id"]
        note = (input_values[0] if input_values else "").strip()
        if note:
            history = workflow.list_instance_history(conn, instance_id)
            if history:  # attaches to the most recent transition - see workflow.list_instance_history (DESC order)
                workflow.add_history_note(conn, history[0]["history_id"], note)

        version = workflow.get_version(conn, version_id) if version_id is not None else None
        instances = [workflow.get_or_create_instance(conn, version_id)] if version_id is not None else []
        steps = version["steps"] if version else []
        # The note input this click came from only exists while this
        # instance's history is expanded - keep it expanded so the just-
        # added note is immediately visible instead of the panel collapsing
        # back to a bare toggle right after a successful save.
        return _render_instance_list(conn, version_id, expanded_history_instance_id)

    @app.callback(
        Output("instance-list", "children", allow_duplicate=True),
        Output("expanded-history-instance-id", "data"),
        Input({"type": "history-toggle-btn", "instance_id": ALL}, "n_clicks"),
        State("expanded-history-instance-id", "data"),
        State("version-picker", "value"),
        prevent_initial_call=True,
    )
    def toggle_instance_history(_clicks, expanded_history_instance_id, version_id):
        # Same remount-vs-click guard as edit_role/edit_instance_name - this
        # callback's own Output (instance-list) contains every toggle button
        # it listens on.
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update

        instance_id = triggered["instance_id"]
        # An accordion, not independent checkboxes: clicking the instance
        # that's already open closes it, clicking a different one switches
        # to it - at most one instance's history is expanded at a time,
        # which is what keeps a page with many instances scannable.
        new_expanded = None if instance_id == expanded_history_instance_id else instance_id

        version = workflow.get_version(conn, version_id) if version_id is not None else None
        instances = [workflow.get_or_create_instance(conn, version_id)] if version_id is not None else []
        steps = version["steps"] if version else []
        return (
            _render_instance_list(conn, version_id, new_expanded),
            new_expanded,
        )

    @app.callback(
        Output("step-detail-backdrop", "style"),
        Output("step-detail-title", "children"),
        Output("step-detail-owner-input", "value"),
        Output("step-detail-duty-input", "value"),
        Output("step-detail-input-input", "value"),
        Output("step-detail-output-input", "value"),
        Output("step-detail-acceptance-criteria-input", "value"),
        Output("step-detail-notification-subject-input", "value"),
        Output("step-detail-sla-input", "value"),
        Output("step-detail-optional-checkbox", "value"),
        Output("step-detail-template-current", "children"),
        Output("step-detail-template-actions", "style"),
        Output("editing-step-detail-id", "data"),
        Output("step-detail-save-status", "children"),
        Input({"type": "step-detail-btn", "step_id": ALL}, "n_clicks"),
        Input("step-detail-close-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_or_close_step_detail(_open_clicks, _close_clicks):
        # Deliberately does NOT also listen on step-detail-save-btn: that
        # button's own callback (save_step_detail, below) needs to read
        # editing-step-detail-id as State to know *which* step to persist -
        # if this callback also fired on the same click and cleared that
        # store, the two would race to decide the store's value before
        # save_step_detail ever reads it. Splitting "which step is open"
        # from "commit this step's fields" so each store is only ever
        # written by one trigger avoids that entirely.
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return (no_update,) * 14

        if triggered == "step-detail-close-btn":
            result = [no_update] * 14
            result[0] = layout.step_detail_backdrop_style(hidden=True)
            result[12] = None
            return tuple(result)

        step_id = triggered["step_id"]
        step = workflow.get_step(conn, step_id)
        if step is None:
            return (no_update,) * 14
        current_text, actions_style = layout.step_template_status(step)
        return (
            layout.step_detail_backdrop_style(hidden=False),
            step["label"],
            step["owner"] or "",
            step["duty"] or "",
            step["input_desc"] or "",
            step["output_desc"] or "",
            step["acceptance_criteria"] or "",
            step["notification_subject"] or "",
            step["sla_days"],
            ["optional"] if step["is_optional"] else [],
            current_text,
            actions_style,
            step_id,
            "",
        )

    @app.callback(
        Output("step-detail-backdrop", "style", allow_duplicate=True),
        Output("editing-step-detail-id", "data", allow_duplicate=True),
        Output("step-details-list", "children", allow_duplicate=True),
        Output("status-summary-content", "children", allow_duplicate=True),
        Output("instance-list", "children", allow_duplicate=True),
        Input("step-detail-save-btn", "n_clicks"),
        State("editing-step-detail-id", "data"),
        State("step-detail-owner-input", "value"),
        State("step-detail-duty-input", "value"),
        State("step-detail-input-input", "value"),
        State("step-detail-output-input", "value"),
        State("step-detail-acceptance-criteria-input", "value"),
        State("step-detail-notification-subject-input", "value"),
        State("step-detail-sla-input", "value"),
        State("step-detail-optional-checkbox", "value"),
        State("version-picker", "value"),
        State("expanded-history-instance-id", "data"),
        prevent_initial_call=True,
    )
    def save_step_detail(
        n_clicks,
        step_id,
        owner,
        duty,
        input_desc,
        output_desc,
        acceptance_criteria,
        notification_subject,
        sla_days,
        optional_value,
        version_id,
        expanded_history_instance_id,
    ):
        if not n_clicks or step_id is None:
            return (no_update,) * 5
        sla_days_int = int(sla_days) if sla_days not in (None, "") else None
        workflow.update_step_details(
            conn,
            step_id,
            owner,
            duty,
            input_desc,
            output_desc,
            acceptance_criteria,
            sla_days_int,
            "optional" in (optional_value or []),
            notification_subject,
        )

        version = workflow.get_version(conn, version_id) if version_id is not None else None
        steps = version["steps"] if version else []
        instances = [workflow.get_or_create_instance(conn, version_id)] if version_id is not None else []
        summary = workflow.step_status_summary(conn, version_id) if version_id is not None else []
        return (
            layout.step_detail_backdrop_style(hidden=True),
            None,
            layout.build_step_details_list(steps),
            layout.build_status_summary(summary),
            _render_instance_list(conn, version_id, expanded_history_instance_id),
        )

    @app.callback(
        Output("step-detail-template-current", "children", allow_duplicate=True),
        Output("step-detail-template-actions", "style", allow_duplicate=True),
        Output("step-details-list", "children", allow_duplicate=True),
        Output("last-template-upload-hash", "data"),
        Input("step-detail-template-upload", "contents"),
        State("step-detail-template-upload", "filename"),
        State("editing-step-detail-id", "data"),
        State("version-picker", "value"),
        State("last-template-upload-hash", "data"),
        prevent_initial_call=True,
    )
    def upload_step_template(contents, filename, step_id, version_id, last_hash):
        if not contents or step_id is None:
            return no_update, no_update, no_update, no_update
        # Same dcc.Upload multi-fire quirk import_version's docstring
        # explains - dedup by (step_id, content) so one real upload can't
        # write and re-write the file 2-3 times over.
        content_hash = hashlib.sha256(f"{step_id}:{contents}".encode("utf-8")).hexdigest()
        if content_hash == last_hash:
            return no_update, no_update, no_update, no_update
        _header, b64data = contents.split(",", 1)
        raw_bytes = base64.b64decode(b64data)
        workflow.save_step_template(conn, step_id, filename or "template", raw_bytes)

        step = workflow.get_step(conn, step_id)
        current_text, actions_style = layout.step_template_status(step)
        version = workflow.get_version(conn, version_id) if version_id is not None else None
        steps = version["steps"] if version else []
        return current_text, actions_style, layout.build_step_details_list(steps), content_hash

    @app.callback(
        Output("step-detail-template-current", "children", allow_duplicate=True),
        Output("step-detail-template-actions", "style", allow_duplicate=True),
        Output("step-details-list", "children", allow_duplicate=True),
        Input("step-detail-template-clear-btn", "n_clicks"),
        State("editing-step-detail-id", "data"),
        State("version-picker", "value"),
        prevent_initial_call=True,
    )
    def clear_step_template(n_clicks, step_id, version_id):
        if not n_clicks or step_id is None:
            return no_update, no_update, no_update
        workflow.clear_step_template(conn, step_id)

        current_text, actions_style = layout.step_template_status(None)
        version = workflow.get_version(conn, version_id) if version_id is not None else None
        steps = version["steps"] if version else []
        return current_text, actions_style, layout.build_step_details_list(steps)

    @app.callback(
        Output("step-detail-download", "data"),
        Input("step-detail-template-download-btn", "n_clicks"),
        State("editing-step-detail-id", "data"),
        prevent_initial_call=True,
    )
    def download_step_template(n_clicks, step_id):
        if not n_clicks or step_id is None:
            return no_update
        step = workflow.get_step(conn, step_id)
        if not step or not step.get("template_path"):
            return no_update
        full_path = config.PROJECT_ROOT / step["template_path"]
        if not full_path.exists():
            return no_update
        return dcc.send_file(str(full_path), filename=step["template_original_name"])

    @app.callback(
        Output("mirror-sync-status", "children"),
        Input("mirror-sync-interval", "n_intervals"),
    )
    def sync_mirror_tick(_n_intervals):
        # Refreshes db/fpna.mirror.duckdb from the app's own live connection
        # every 5s (see db.sync_mirror for why this can't just be an external
        # file copy) - lets any other tool inspect current data without ever
        # stopping this dashboard.
        #
        # The same tick is also where scheduled kick-offs fire. Piggy-backing
        # on an interval that already exists (rather than adding a second one)
        # keeps there being exactly one clock in the app, and the catch-up
        # semantics mean a schedule that came due while the dashboard was
        # closed still fires on the first tick after it reopens - see
        # workflow.due_schedules.
        _run_due_schedules()
        synced = db.sync_mirror(conn)
        # Bounds how much is ever sitting in the WAL: with a checkpoint every
        # cycle, an abrupt kill can lose at most one tick's writes instead of
        # a whole session's, and the WAL never grows into something DuckDB
        # struggles to replay. Best-effort by design - see db.checkpoint.
        db.checkpoint(conn)
        now = datetime.now().strftime("%H:%M:%S")
        if synced:
            return f"کپی زنده ساعت {now} همگام‌سازی شد ← {config.MIRROR_DB_PATH}"
        return f"کپی زنده ساعت {now} رد شد (فایل مپی جای دیگری مشغول است - دوباره تلاش می‌شود) ← {config.MIRROR_DB_PATH}"

    def _run_due_schedules() -> None:
        """Start every workflow whose schedule has come due, then mark it run.

        mark_schedule_run happens even if the kick-off itself reported a
        problem: a schedule that keeps failing must not re-fire on every
        5-second tick forever, spamming the channel. Notification failures
        are already best-effort and logged (see _notify_step_change).
        """
        for schedule in workflow.due_schedules(conn):
            result = workflow.start_workflow(conn, schedule["version_id"])
            if result["ok"]:
                _notify_steps(
                    conn,
                    result["instance_id"],
                    schedule["version_id"],
                    result["newly_actionable"],
                    "advance",
                )
            workflow.mark_schedule_run(conn, schedule["schedule_id"])

    @app.callback(
        Output("schedule-list", "children"),
        Output("schedule-add-status", "children"),
        Input("schedule-add-btn", "n_clicks"),
        Input({"type": "schedule-toggle-btn", "schedule_id": ALL}, "n_clicks"),
        Input({"type": "schedule-delete-btn", "schedule_id": ALL}, "n_clicks"),
        State("schedule-version-picker", "value"),
        State("schedule-date-picker", "date"),
        State("schedule-time-input", "value"),
        prevent_initial_call=True,
    )
    def manage_schedules(_add_clicks, _toggle_clicks, _delete_clicks, version_id, date_value, time_value):
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update

        status = ""
        if triggered == "schedule-add-btn":
            if version_id is None:
                return no_update, "اول یک گردش‌کار را انتخاب کنید."
            if not date_value:
                return no_update, "تاریخ را انتخاب کنید."
            try:
                hour, minute = (time_value or "09:00").strip().split(":")
                run_at = datetime.fromisoformat(str(date_value)[:10]).replace(
                    hour=int(hour), minute=int(minute), second=0, microsecond=0
                )
            except (ValueError, TypeError):
                return no_update, "ساعت را به صورت HH:MM وارد کنید (مثلاً 09:00)."
            workflow.create_schedule(conn, version_id, run_at)
            status = f"زمان‌بندی برای {run_at:%Y-%m-%d %H:%M} ثبت شد."
        elif triggered["type"] == "schedule-toggle-btn":
            current = next(
                (s for s in workflow.list_schedules(conn) if s["schedule_id"] == triggered["schedule_id"]),
                None,
            )
            if current is not None:
                workflow.set_schedule_enabled(conn, triggered["schedule_id"], not current["enabled"])
        else:
            workflow.delete_schedule(conn, triggered["schedule_id"])
            status = "زمان‌بندی حذف شد."

        return layout.build_schedule_rows(workflow.list_schedules(conn)), status

    @app.callback(
        Output("tour-backdrop", "style"),
        Output("tour-step-counter", "children"),
        Output("tour-step-title", "children"),
        Output("tour-step-body", "children"),
        Output("tour-step-dots", "children"),
        Output("tour-prev-btn", "style"),
        Output("tour-next-btn", "style"),
        Output("tour-finish-btn", "style"),
        Output("tour-step-store", "data"),
        Input("tour-seen-store", "data"),
        Input("tour-next-btn", "n_clicks"),
        Input("tour-prev-btn", "n_clicks"),
        Input("tour-skip-btn", "n_clicks"),
        Input("tour-finish-btn", "n_clicks"),
        Input("tour-close-btn", "n_clicks"),
        State("tour-step-store", "data"),
    )
    def render_tour(seen, _next_clicks, _prev_clicks, _skip_clicks, _finish_clicks, _close_clicks, step):
        # Fires once on every page load too (prevent_initial_call defaults to
        # False), which is exactly what shows the tour automatically for a
        # browser that has never dismissed it: `seen` on that first call is
        # already the value dcc.Store restored from localStorage, not some
        # placeholder, since storage_type="local" hydrates before callbacks
        # run.
        triggered = ctx.triggered_id
        if triggered == "tour-next-btn":
            step = min(step + 1, len(layout.TOUR_STEPS) - 1)
        elif triggered == "tour-prev-btn":
            step = max(step - 1, 0)

        hide = bool(seen) or triggered in ("tour-skip-btn", "tour-finish-btn", "tour-close-btn")
        current = layout.TOUR_STEPS[step]
        is_last = step == len(layout.TOUR_STEPS) - 1
        return (
            layout.tour_backdrop_style(hidden=hide),
            # Deliberately "مرحله 1 از 5", never a bare "1 / 5": a run of
            # digits/slash with no Persian (strong-RTL) character anywhere
            # in the same block has no anchor for the browser's bidi
            # algorithm, which then lays the neutral "N / N" run out
            # according to the inherited RTL paragraph direction and
            # visually swaps the two numbers - confirmed live, this showed
            # as "5 / 1" on step 1 before the surrounding Persian words were
            # added here.
            f"مرحله {step + 1} از {len(layout.TOUR_STEPS)}",
            current["title"],
            current["body"],
            layout.build_tour_dots(step),
            layout.tour_nav_style(layout.TOUR_PREV_STYLE_BASE, visible=step > 0),
            layout.tour_nav_style({}, visible=not is_last),
            layout.tour_nav_style({}, visible=is_last),
            step,
        )

    @app.callback(
        Output("tour-seen-store", "data"),
        Input("tour-skip-btn", "n_clicks"),
        Input("tour-finish-btn", "n_clicks"),
        Input("tour-close-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def dismiss_tour(_skip_clicks, _finish_clicks, _close_clicks):
        # Separate from render_tour (which hides the overlay immediately on
        # the same click) so tour-seen-store - the one thing that must
        # persist to localStorage - is only ever written here, never also
        # read as an Input on the same callback that writes it.
        return True

    # --- light/dark theme toggle - both halves are clientside on purpose ---
    # Every color in this app is a var(--fpa-*) lookup (see layout.py's
    # token comment and style.css), so the *entire* re-paint is just one
    # attribute write on <html> - doing that over a normal Python callback
    # would mean a network round-trip and a "flash" while it's in flight for
    # something that has to feel instant, like flipping a light switch.
    app.clientside_callback(
        """
        function(n_clicks, current) {
            if (!n_clicks) { return window.dash_clientside.no_update; }
            return current === "light" ? "dark" : "light";
        }
        """,
        Output("theme-store", "data"),
        Input("theme-toggle-btn", "n_clicks"),
        State("theme-store", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(theme) {
            // Set on <html>, not on #fpa-app-root: Dash portals some of its
            // own UI (dropdown popups, this app's dcc.ConfirmDialog) to
            // sit outside the app's own div in the real DOM, and CSS custom
            // properties only reach elements the attribute's own subtree
            // contains - html is the one ancestor everything is under.
            document.documentElement.setAttribute("data-theme", theme || "dark");
            return theme === "light" ? "☀️" : "🌙";
        }
        """,
        Output("theme-toggle-btn", "children"),
        Input("theme-store", "data"),
    )

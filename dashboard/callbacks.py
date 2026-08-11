"""Dash callback wiring for the FP-A Budgeting Workflow Designer.

The drag-and-drop canvas itself is owned by client-side JS
(assets/dragdrop.js) - it writes the current step list into
workflow-steps-store via dash_clientside.set_props(). Everything here is
the server-side half: version switching/creation/activation, persisting
the step list on Save, managing roles, and instances (create + mark
current step).
"""

from datetime import datetime

import duckdb
from dash import ALL, Input, Output, State, ctx, no_update

import layout
from fpna import config, db, workflow

DEFAULT_VERSION_NAME = "گردش‌کار جدید"


def _load_view(conn: duckdb.DuckDBPyConnection, version_id: int | None):
    versions = workflow.list_versions(conn)
    version = workflow.get_version(conn, version_id) if version_id is not None else None
    instances = workflow.list_instances(conn, version_id) if version_id is not None else []
    return versions, version, instances


def register_callbacks(app, conn: duckdb.DuckDBPyConnection) -> None:
    @app.callback(
        Output("page-content", "children"),
        Output("module-header", "children"),
        Output({"type": "module-nav-btn", "module": ALL}, "className"),
        Output("active-module", "data"),
        Input({"type": "module-nav-btn", "module": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def switch_module(_clicks):
        # Same remount-vs-click guard as edit_role/mark_current_step - see
        # those for why: nothing here re-renders the nav buttons themselves,
        # but Dash still fires this callback once at hydration with every
        # n_clicks already at its initial 0, which must not be mistaken for
        # a real click on module "0"/whichever sorts first.
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update, no_update, no_update

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
            instances = workflow.list_instances(conn, selected_version_id)
            content = layout.build_module_content(module_id, roles, versions, selected_version, instances)
        else:
            content = layout.build_module_content(module_id, [], [], None, [])

        return content, header, classnames, module_id

    @app.callback(
        Output("version-bar-container", "children"),
        Output("fpa-steps-payload", "data-steps"),
        Output("fpa-steps-payload", "data-version-id"),
        Output("instance-list", "children", allow_duplicate=True),
        Output("workflow-steps-store", "data"),
        Output("version-action-status", "children"),
        Output("new-version-name", "value"),
        Input("version-picker", "value"),
        Input("create-version-btn", "n_clicks"),
        Input("activate-version-btn", "n_clicks"),
        State("new-version-name", "value"),
        prevent_initial_call=True,
    )
    def switch_or_create_or_activate(selected_version_id, create_clicks, activate_clicks, new_name):
        triggered = ctx.triggered_id
        status_msg = ""
        reset_name = no_update

        if triggered == "create-version-btn":
            if not create_clicks:
                return (no_update,) * 7
            name = (new_name or "").strip() or DEFAULT_VERSION_NAME
            selected_version_id = workflow.create_version(conn, name)
            status_msg = f"«{name}» به‌عنوان یک پیش‌نویس جدید ایجاد شد."
            reset_name = ""
        elif triggered == "activate-version-btn":
            if not activate_clicks:
                return (no_update,) * 7
            if selected_version_id is None:
                return (no_update,) * 7
            workflow.activate_version(conn, selected_version_id)
            status_msg = "فعال شد - همه‌ی نسخه‌های دیگر اکنون پیش‌نویس هستند."
        # else: triggered == "version-picker" -> plain switch, just re-render below.

        versions, version, instances = _load_view(conn, selected_version_id)
        steps = version["steps"] if version else []
        return (
            layout.build_version_bar(versions, version),
            layout.steps_json(steps),
            layout.canvas_render_token(version),
            layout.build_instance_list(instances, steps),
            [{"role_id": s["role_id"], "label": s["label"]} for s in steps],
            status_msg,
            reset_name,
        )

    @app.callback(
        Output("fpa-steps-payload", "data-steps", allow_duplicate=True),
        Output("fpa-steps-payload", "data-version-id", allow_duplicate=True),
        Output("instance-list", "children", allow_duplicate=True),
        Output("workflow-steps-store", "data", allow_duplicate=True),
        Output("save-steps-status", "children"),
        Input("save-steps-btn", "n_clicks"),
        State("version-picker", "value"),
        State("workflow-steps-store", "data"),
        prevent_initial_call=True,
    )
    def save_steps(n_clicks, version_id, steps_data):
        if not n_clicks:
            return no_update, no_update, no_update, no_update, no_update
        if version_id is None:
            return no_update, no_update, no_update, no_update, "اول یک نسخه را انتخاب یا ایجاد کنید."

        workflow.save_steps(conn, version_id, steps_data or [])

        version = workflow.get_version(conn, version_id)
        instances = workflow.list_instances(conn, version_id)
        steps = version["steps"] if version else []
        return (
            layout.steps_json(steps),
            layout.canvas_render_token(version),
            layout.build_instance_list(instances, steps),
            [{"role_id": s["role_id"], "label": s["label"]} for s in steps],
            f"ذخیره شد — {len(steps)} مرحله.",
        )

    @app.callback(
        Output("role-palette", "children", allow_duplicate=True),
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
        return layout.build_role_palette(roles), f"«{name}» اضافه شد.", ""

    @app.callback(
        Output("role-palette", "children", allow_duplicate=True),
        Output("editing-role-id", "data"),
        Input({"type": "role-chip-label", "role_id": ALL}, "n_clicks"),
        Input({"type": "role-name-input", "role_id": ALL}, "n_submit"),
        Input({"type": "role-name-save", "role_id": ALL}, "n_clicks"),
        Input({"type": "role-name-cancel", "role_id": ALL}, "n_clicks"),
        State({"type": "role-name-input", "role_id": ALL}, "value"),
        prevent_initial_call=True,
    )
    def edit_role(_label_clicks, _submits, _save_clicks, _cancel_clicks, input_values):
        # Same remount-vs-click ambiguity fixed for mark_current_step below:
        # this callback's own Output (role-palette) contains every id it
        # listens on, so re-rendering the palette for *any* reason (e.g.
        # clicking a different role's label) makes the whole pattern-matched
        # set look like it just "changed" too. Only trust a genuine trigger
        # with both a real id and a truthy value.
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update

        role_id = triggered["role_id"]
        if triggered["type"] == "role-chip-label":
            editing_role_id = role_id
        elif triggered["type"] == "role-name-cancel":
            editing_role_id = None
        else:  # "role-name-save" click, or Enter (n_submit) inside the input
            new_name = (input_values[0] if input_values else "").strip()
            if new_name:
                workflow.rename_role(conn, role_id, new_name)
            editing_role_id = None

        roles = workflow.list_roles(conn)
        return layout.build_role_palette(roles, editing_role_id=editing_role_id), editing_role_id

    @app.callback(
        Output("instance-list", "children", allow_duplicate=True),
        Output("create-instance-status", "children"),
        Output("new-instance-name", "value"),
        Input("create-instance-btn", "n_clicks"),
        State("version-picker", "value"),
        State("new-instance-name", "value"),
        prevent_initial_call=True,
    )
    def create_instance(n_clicks, version_id, name):
        if not n_clicks:
            return no_update, no_update, no_update
        if version_id is None:
            return no_update, "اول یک نسخه را انتخاب یا ایجاد کنید.", no_update
        name = (name or "").strip()
        if not name:
            return no_update, "نام نمونه را وارد کنید.", no_update

        workflow.create_instance(conn, version_id, name)

        version = workflow.get_version(conn, version_id)
        instances = workflow.list_instances(conn, version_id)
        steps = version["steps"] if version else []
        return layout.build_instance_list(instances, steps), f"«{name}» ایجاد شد.", ""

    @app.callback(
        Output("instance-list", "children", allow_duplicate=True),
        Output("editing-instance-id", "data"),
        Input({"type": "instance-name-label", "instance_id": ALL}, "n_clicks"),
        Input({"type": "instance-name-input", "instance_id": ALL}, "n_submit"),
        Input({"type": "instance-name-save", "instance_id": ALL}, "n_clicks"),
        Input({"type": "instance-name-cancel", "instance_id": ALL}, "n_clicks"),
        State({"type": "instance-name-input", "instance_id": ALL}, "value"),
        State("version-picker", "value"),
        prevent_initial_call=True,
    )
    def edit_instance_name(_label_clicks, _submits, _save_clicks, _cancel_clicks, input_values, version_id):
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
        instances = workflow.list_instances(conn, version_id) if version_id is not None else []
        steps = version["steps"] if version else []
        return layout.build_instance_list(instances, steps, editing_instance_id=editing_instance_id), editing_instance_id

    @app.callback(
        Output("delete-instance-confirm", "displayed"),
        Output("delete-instance-confirm", "message"),
        Output("pending-delete-instance-id", "data"),
        Input({"type": "delete-instance-btn", "instance_id": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def ask_delete_instance(_clicks):
        # Delete has no undo (unlike rename), so it always goes through this
        # confirm step - the real delete only happens in
        # confirm_delete_instance below, once the browser's native dialog
        # comes back with a "submit".
        triggered = ctx.triggered_id
        if triggered is None or not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update, no_update

        instance_id = triggered["instance_id"]
        instances = workflow.list_instances(conn)
        match = next((i for i in instances if i["instance_id"] == instance_id), None)
        name = match["name"] if match else ""
        return True, f"نمونه‌ی «{name}» حذف شود؟ این کار قابل بازگشت نیست.", instance_id

    @app.callback(
        Output("instance-list", "children", allow_duplicate=True),
        Output("delete-instance-confirm", "displayed", allow_duplicate=True),
        Input("delete-instance-confirm", "submit_n_clicks"),
        State("pending-delete-instance-id", "data"),
        State("version-picker", "value"),
        prevent_initial_call=True,
    )
    def confirm_delete_instance(_submit_clicks, pending_instance_id, version_id):
        if not pending_instance_id:
            return no_update, False
        workflow.delete_instance(conn, pending_instance_id)

        version = workflow.get_version(conn, version_id) if version_id is not None else None
        instances = workflow.list_instances(conn, version_id) if version_id is not None else []
        steps = version["steps"] if version else []
        return layout.build_instance_list(instances, steps), False

    @app.callback(
        Output("instance-list", "children", allow_duplicate=True),
        Input({"type": "set-current-step", "instance_id": ALL, "step_id": ALL}, "n_clicks"),
        State("version-picker", "value"),
        prevent_initial_call=True,
    )
    def mark_current_step(_all_clicks, version_id):
        # triggered_id is None when Dash fires this because the whole set of
        # pattern-matched pills was just replaced (e.g. instance-list
        # re-rendered by an unrelated callback), not because one was really
        # clicked - the same remount-vs-click ambiguity fixed in XP-A's
        # button callbacks. Only a genuine single click gives a real id here.
        triggered = ctx.triggered_id
        if triggered is None:
            return no_update
        if not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update
        workflow.set_current_step(conn, triggered["instance_id"], triggered["step_id"])

        version = workflow.get_version(conn, version_id) if version_id is not None else None
        instances = workflow.list_instances(conn, version_id) if version_id is not None else []
        steps = version["steps"] if version else []
        return layout.build_instance_list(instances, steps)

    @app.callback(
        Output("mirror-sync-status", "children"),
        Input("mirror-sync-interval", "n_intervals"),
    )
    def sync_mirror_tick(_n_intervals):
        # Refreshes db/fpna.mirror.duckdb from the app's own live connection
        # every 5s (see db.sync_mirror for why this can't just be an external
        # file copy) - lets any other tool inspect current data without ever
        # stopping this dashboard.
        synced = db.sync_mirror(conn)
        now = datetime.now().strftime("%H:%M:%S")
        if synced:
            return f"کپی زنده ساعت {now} همگام‌سازی شد ← {config.MIRROR_DB_PATH}"
        return f"کپی زنده ساعت {now} رد شد (فایل مپی جای دیگری مشغول است - دوباره تلاش می‌شود) ← {config.MIRROR_DB_PATH}"

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

"""Dash layout for the FP-A Budgeting Workflow Designer.

Visual language is deliberately identical to XP-A's dashboard (same dark
surfaces, text tokens, and accent) - see the constants below, ported
straight from xpna's dashboard/layout.py so the two projects read as one
family, per the user's request.

Render helpers here (build_role_palette, build_canvas_children,
build_instance_list, build_version_bar) are used both for the page's first
paint (called directly, with data already loaded) and by callbacks.py to
refresh just one container after an interaction - same function, two
call sites, so the two can never drift apart.
"""

import json
from datetime import datetime

from dash import dcc, html

# ---- Color tokens ----
# Every one of these is a var(--fpa-*) lookup, not a literal color - the
# actual light/dark values live in assets/style.css's :root and
# :root[data-theme="light"] blocks. That's what makes the theme toggle
# (theme-toggle-btn / callbacks.apply_theme) instant: it only ever flips one
# attribute on <html>, and every element built from these constants re-paints
# itself for free because it was never holding a literal color to begin with.
# Never reintroduce a literal hex/rgba here or at a call site - add a token
# to style.css instead, or that one spot silently stops following the theme.
SURFACE = "var(--fpa-surface)"
PAGE = "var(--fpa-page)"
SIDEBAR = "var(--fpa-surface)"
TEXT_PRIMARY = "var(--fpa-text)"
TEXT_SECONDARY = "var(--fpa-text-secondary)"
TEXT_MUTED = "var(--fpa-text-muted)"
GRIDLINE = "var(--fpa-border)"
BORDER = "var(--fpa-border)"
ACCENT = "var(--fpa-accent)"

GOOD_COLOR = "var(--fpa-good)"
CRITICAL_COLOR = "var(--fpa-critical)"

CARD_STYLE = {
    "background": SURFACE,
    "border": f"1px solid {BORDER}",
    "borderRadius": "10px",
    "padding": "20px 24px",
}

# The same 5-hue set used to seed dim_role in data/seed/roles.csv - kept
# here too so a freshly-created custom role (via the "+ Add role" form) can
# be auto-assigned the next color in the same family instead of a random one.
ROLE_COLOR_CYCLE = ["#0891b2", "#8b5cf6", "#ec4899", "#d97706", "#0f766e"]


def build_role_palette(roles: list[dict], editing_role_id: int | None = None):
    """`editing_role_id` swaps exactly one chip (if its role_id matches) into
    an inline rename form instead of the normal draggable chip - see
    callbacks.edit_role, which is the only thing that ever sets it.
    """
    input_style = {
        "width": "100%",
        "background": "var(--fpa-surface)",
        "border": "1px solid var(--fpa-border)",
        "borderRadius": "6px",
        "color": "var(--fpa-text)",
        "padding": "4px 8px",
        "fontSize": "12.5px",
    }
    chips = []
    for role in roles:
        if role["role_id"] == editing_role_id:
            chips.append(
                html.Div(
                    className="fpa-role-chip fpa-role-chip-editing",
                    style={
                        "--role-color": role["color_hex"],
                        "flexDirection": "column",
                        "alignItems": "stretch",
                        "gap": "6px",
                    },
                    children=[
                        dcc.Input(
                            id={"type": "role-name-input", "role_id": role["role_id"]},
                            value=role["role_name"],
                            type="text",
                            placeholder="نام نقش",
                            autoFocus=True,
                            style=input_style,
                        ),
                        dcc.Input(
                            id={"type": "role-assignee-name-input", "role_id": role["role_id"]},
                            value=role.get("assignee_name") or "",
                            type="text",
                            placeholder="نام مسئول (اختیاری)",
                            style=input_style,
                        ),
                        dcc.Input(
                            id={"type": "role-assignee-email-input", "role_id": role["role_id"]},
                            value=role.get("assignee_email") or "",
                            type="email",
                            placeholder="ایمیل مسئول (اختیاری)",
                            style=input_style,
                        ),
                        html.Div(
                            [
                                html.Button(
                                    "🗑",
                                    id={"type": "role-delete-btn", "role_id": role["role_id"]},
                                    n_clicks=0,
                                    className="fpa-chip-icon-btn fpa-btn-danger",
                                    title="حذف این نقش",
                                ),
                                html.Div(style={"flex": "1"}),
                                html.Button(
                                    "✓",
                                    id={"type": "role-name-save", "role_id": role["role_id"]},
                                    n_clicks=0,
                                    className="fpa-chip-icon-btn",
                                    title="ذخیره",
                                ),
                                html.Button(
                                    "×",
                                    id={"type": "role-name-cancel", "role_id": role["role_id"]},
                                    n_clicks=0,
                                    className="fpa-chip-icon-btn",
                                    title="انصراف",
                                ),
                            ],
                            style={"display": "flex", "gap": "6px", "justifyContent": "flex-end", "alignItems": "center"},
                        ),
                    ],
                )
            )
        else:
            label_children = [
                html.Span(
                    role["role_name"],
                    id={"type": "role-chip-label", "role_id": role["role_id"]},
                    n_clicks=0,
                    className="fpa-role-chip-label",
                    title="برای ویرایش نام و مسئول کلیک کنید",
                )
            ]
            if role.get("assignee_name"):
                label_children.append(
                    html.Div(
                        role["assignee_name"],
                        style={"fontSize": "10.5px", "color": "var(--fpa-text-secondary)", "fontWeight": "400"},
                    )
                )
            chips.append(
                html.Div(
                    className="fpa-role-chip",
                    draggable="true",
                    style={"--role-color": role["color_hex"]},
                    **{
                        "data-role-id": role["role_id"],
                        "data-role-name": role["role_name"],
                        "data-color": role["color_hex"],
                    },
                    children=[
                        html.Span("⠿", className="fpa-drag-handle"),
                        html.Span(role["role_name"][:1], className="fpa-role-badge"),
                        html.Div(label_children),
                    ],
                )
            )
    return chips


def build_canvas_children(steps: list[dict]):
    """The chips shown inside #fpa-canvas for one version's step list.
    `steps` items need: step_id, role_id, role_name, color_hex, label.
    """
    if not steps:
        return html.Div(
            [
                html.Div("+", className="fpa-plus"),
                # Kept identical to dragdrop.js's own copy of this same empty
                # state (see that file) - client-side JS repaints this same
                # message any time __fpaSteps becomes empty, so the two must
                # never drift apart.
                html.Div("یک نقش را اینجا بکشید تا اولین مرحله اضافه شود"),
            ],
            className="fpa-canvas-empty",
        )
    children = []
    for i, step in enumerate(steps):
        if i > 0:
            children.append(html.Span("→", className="fpa-arrow"))
        children.append(
            html.Div(
                className="fpa-chip",
                draggable="true",
                style={"--role-color": step["color_hex"]},
                **{
                    "data-key": f"s{step['step_id']}",
                    "data-role-id": step["role_id"],
                    "data-role-name": step["role_name"],
                    "data-color": step["color_hex"],
                    "data-label": step["label"],
                },
                children=[
                    html.Span(str(i + 1), className="fpa-step-index"),
                    html.Span((step["role_name"] or step["label"])[:1], className="fpa-role-badge"),
                    html.Span(step["label"]),
                    html.Button("×", className="fpa-remove", **{"data-key": f"s{step['step_id']}"}),
                ],
            )
        )
    return children


# Display-only Persian labels for the 'draft'/'active' values stored in
# workflow_version.status - the stored value itself is never translated,
# only what's rendered on screen.
STATUS_LABEL_FA = {"active": "فعال", "draft": "پیش‌نویس"}


def build_status_badge(status: str):
    color = GOOD_COLOR if status == "active" else TEXT_MUTED
    bg = "var(--fpa-good-soft)" if status == "active" else "var(--fpa-hover-overlay)"
    return html.Span(
        STATUS_LABEL_FA.get(status, status),
        style={
            "color": color,
            "background": bg,
            "border": f"1px solid {color}",
            "borderRadius": "999px",
            "padding": "4px 12px",
            "fontSize": "11.5px",
            "fontWeight": "700",
            "letterSpacing": "0.03em",
        },
    )


def version_options(versions: list[dict]):
    return [
        {
            "label": f"{v['name']} — {STATUS_LABEL_FA.get(v['status'], v['status'])} ({v['step_count']} مرحله)",
            "value": v["version_id"],
        }
        for v in versions
    ]


def build_version_bar(versions: list[dict], selected_version: dict):
    # Split into two cards per the user's request - the old single crowded
    # row mixed "make a brand-new workflow" (name + create) with "pick an
    # existing one to work on" (dropdown + activate + export/import), which
    # read as one undifferentiated wall of controls. Now each concern gets
    # its own card with its own heading; every id below is unchanged from
    # the single-row version, so callbacks.py needs no changes - only this
    # function's markup moved.
    new_version_card = html.Div(
        style={**CARD_STYLE, "flex": "1", "minWidth": "260px"},
        children=[
            html.Div("گردش‌کار جدید", style={"fontWeight": "600", "marginBottom": "2px"}),
            html.Div(
                "یک گردش‌کار خالی برای طراحی از ابتدا بسازید.",
                style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px"},
            ),
            html.Label("نام گردش‌کار", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
            dcc.Input(
                id="new-version-name",
                type="text",
                placeholder="مثلاً «تصویب بودجه‌ی ۱۴۰۵»",
                style={"width": "100%", "height": "34px", "marginTop": "6px", "marginBottom": "12px"},
            ),
            html.Button("+ ایجاد گردش‌کار جدید", id="create-version-btn", n_clicks=0, style={"width": "100%"}),
        ],
    )

    select_version_card = html.Div(
        style={**CARD_STYLE, "flex": "2", "minWidth": "360px"},
        children=[
            html.Div("انتخاب گردش‌کار", style={"fontWeight": "600", "marginBottom": "2px"}),
            html.Div(
                "یک گردش‌کار موجود را انتخاب کنید تا مراحلش را در پایین طراحی و ویرایش کنید.",
                style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px"},
            ),
            html.Div(
                style={"display": "flex", "gap": "14px", "alignItems": "flex-end", "flexWrap": "wrap"},
                children=[
                    html.Div(
                        [
                            html.Label("نسخه", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
                            dcc.Dropdown(
                                id="version-picker",
                                options=version_options(versions),
                                value=selected_version["version_id"] if selected_version else None,
                                clearable=False,
                                style={"width": "300px"},
                            ),
                        ]
                    ),
                    html.Div(
                        id="version-status-badge",
                        children=build_status_badge(selected_version["status"]) if selected_version else "",
                    ),
                    # No "فعال‌سازی" button anymore - workflow_version.status
                    # doesn't gate anything else in the app yet (checked: not
                    # read anywhere but this badge), so a control to flip it
                    # was pure overhead. The badge itself stays as a read-only
                    # trace of whichever version was marked active before -
                    # nothing left in the UI can change it now.
                    # JSON export/import are occasional, secondary actions (backup /
                    # transfer-between-databases, not part of the everyday design
                    # loop) - icon-only so they don't visually compete with the
                    # primary buttons just before them, same treatment as the
                    # canvas's undo button. Title tooltips carry the full label.
                    html.Button(
                        "📤",
                        id="export-version-btn",
                        n_clicks=0,
                        className="fpa-icon-btn",
                        title="خروجی JSON — دریافت این نسخه (مراحل و جزئیات‌شان، بدون فایل‌های الگو) به‌صورت یک فایل",
                    ),
                    html.Div(
                        dcc.Upload(id="import-version-upload", children="📥", className="fpa-upload-icon-btn"),
                        title="ورودی JSON — ساخت یک نسخه‌ی جدید از یک فایل JSON که قبلاً خروجی گرفته شده",
                    ),
                    dcc.Download(id="version-export-download"),
                ],
            ),
        ],
    )

    return html.Div(
        style={"marginBottom": "20px"},
        children=[
            html.Div(
                style={"display": "flex", "gap": "14px", "alignItems": "stretch", "flexWrap": "wrap"},
                children=[new_version_card, select_version_card],
            ),
            # Shared feedback line for both cards (create/activate messages) -
            # kept as one id since switch_or_create_or_activate already
            # writes a single message regardless of which action fired it.
            html.Div(id="version-action-status", style={"color": TEXT_SECONDARY, "fontSize": "12px", "marginTop": "10px"}),
        ],
    )


def build_instance_row(
    instance: dict,
    steps: list[dict],
    editing_instance_id: int | None = None,
    history: list[dict] | None = None,
    expanded_history_instance_id: int | None = None,
):
    current_step_id = instance["current_step_id"]
    current_index = None
    current_step = None
    for i, s in enumerate(steps):
        if s["step_id"] == current_step_id:
            current_index = i
            current_step = s
            break

    track_children = []
    for i, s in enumerate(steps):
        if i > 0:
            connector_class = "fpa-track-connector"
            if current_index is not None and i <= current_index:
                connector_class += " fpa-connector-done"
            track_children.append(html.Div(className=connector_class))

        if current_index is None:
            css_class = "fpa-pill"
        elif i < current_index:
            css_class = "fpa-pill fpa-pill-done"
        elif i == current_index:
            css_class = "fpa-pill fpa-pill-current"
        else:
            css_class = "fpa-pill fpa-pill-upcoming"

        pill_children = [s["label"]]
        if current_index is not None and i == current_index:
            pill_children.insert(0, html.Span("فعلی", className="fpa-pill-current-label"))

        track_children.append(
            html.Button(
                pill_children,
                id={"type": "set-current-step", "instance_id": instance["instance_id"], "step_id": s["step_id"]},
                className=css_class,
                n_clicks=0,
            )
        )

    # A plain-language answer to "where are we", not just relying on the
    # visual highlight below - this was explicitly called out as unclear.
    if current_index is not None:
        banner = html.Div(
            f"📍 اکنون در: {steps[current_index]['label']}",
            className="fpa-current-banner",
        )
    elif not steps:
        banner = html.Div(
            "این نسخه هنوز مرحله‌ای ندارد - چند مرحله در بوم بالا اضافه کنید.",
            style={"color": TEXT_MUTED, "fontSize": "12.5px", "marginBottom": "10px"},
        )
    else:
        banner = html.Div(
            "مرحله‌ی فعلی مشخص نشده - برای تعیین جایگاه این دوره، یکی از مراحل زیر را کلیک کنید.",
            style={"color": TEXT_MUTED, "fontSize": "12.5px", "marginBottom": "10px"},
        )

    if instance["instance_id"] == editing_instance_id:
        name_area = html.Div(
            [
                dcc.Input(
                    id={"type": "instance-name-input", "instance_id": instance["instance_id"]},
                    value=instance["name"],
                    type="text",
                    autoFocus=True,
                    style={"flex": "1", "minWidth": "0", "height": "30px"},
                ),
                html.Button(
                    "✓",
                    id={"type": "instance-name-save", "instance_id": instance["instance_id"]},
                    n_clicks=0,
                    style={"padding": "4px 10px"},
                    title="ذخیره",
                ),
                html.Button(
                    "×",
                    id={"type": "instance-name-cancel", "instance_id": instance["instance_id"]},
                    n_clicks=0,
                    className="fpa-btn-quiet",
                    style={"padding": "4px 10px"},
                    title="انصراف",
                ),
            ],
            style={"display": "flex", "alignItems": "center", "gap": "6px", "flex": "1"},
        )
    else:
        name_area = html.Div(
            instance["name"],
            id={"type": "instance-name-label", "instance_id": instance["instance_id"]},
            n_clicks=0,
            className="fpa-instance-name fpa-editable-label",
            title="برای ویرایش نام کلیک کنید",
            style={"marginBottom": "0"},
        )

    # Overdue badge: only meaningful once the current step both exists and
    # carries an sla_days (most steps won't - it's opt-in per step, see the
    # step-details editor), computed fresh on every render rather than
    # stored, so it's always right regardless of when the page was loaded.
    header_extra = []
    if current_step is not None and current_step.get("sla_days"):
        elapsed_days = (datetime.now() - instance["updated_at"]).days
        if elapsed_days > current_step["sla_days"]:
            header_extra.append(
                html.Span(
                    f"⚠ {elapsed_days} روز در این مرحله (مهلت {current_step['sla_days']} روز)",
                    style={
                        "color": CRITICAL_COLOR,
                        "background": "var(--fpa-critical-soft)",
                        "border": f"1px solid {CRITICAL_COLOR}",
                        "borderRadius": "999px",
                        "padding": "3px 10px",
                        "fontSize": "11px",
                        "fontWeight": "700",
                    }
                )
            )
    if current_step is not None and current_step.get("is_optional"):
        header_extra.append(
            html.Button(
                "رد کردن این مرحله (اختیاری)",
                id={"type": "skip-step-btn", "instance_id": instance["instance_id"]},
                n_clicks=0,
                className="fpa-btn-quiet",
                style={"border": f"1px solid {BORDER}", "fontSize": "11px", "padding": "4px 10px"},
            )
        )

    return html.Div(
        className="fpa-instance-row",
        children=[
            html.Div(
                [
                    name_area,
                    # No delete button here anymore: this row is the
                    # workflow's own one-and-only progress tracker (see
                    # workflow.get_or_create_instance), not a disposable
                    # extra a user might want to remove - same reasoning as
                    # there being no "delete a workflow version" control.
                    html.Div(
                        header_extra,
                        style={"display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap"},
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "gap": "10px", "marginBottom": "4px", "flexWrap": "wrap"},
            ),
            banner,
            # This track mirrors the canvas's step sequence, so it stays
            # left-to-right too, same reasoning as build_canvas_dropzone.
            html.Div(track_children, className="fpa-track", style={"direction": "ltr"}),
            build_instance_history(
                instance["instance_id"],
                history or [],
                expanded=(instance["instance_id"] == expanded_history_instance_id),
            ),
        ],
    )


def build_instance_history(instance_id: int, history: list[dict], expanded: bool = False):
    """The last 3 transitions (advance/reject/skip) for one instance, plus a
    quick way to attach a note to the most recent one - see
    workflow.list_instance_history/add_history_note. Every click that
    changes an instance's step is logged automatically (workflow.
    set_current_step), so this is never empty once an instance has moved at
    least once; a brand-new instance that hasn't moved yet just shows
    nothing here, which is correct, not a missing feature.

    Collapsed by default (just a small toggle) so a page with many
    instances doesn't turn into a wall of history text - expand on demand
    via {"type": "history-toggle-btn", "instance_id": ...}, tracked in the
    expanded-history-instance-id store (one open at a time).
    """
    if not history:
        return None

    toggle = html.Button(
        ("▴ بستن تاریخچه" if expanded else f"▾ تاریخچه ({len(history)})"),
        id={"type": "history-toggle-btn", "instance_id": instance_id},
        n_clicks=0,
        className="fpa-history-toggle",
    )
    if not expanded:
        return html.Div(toggle, style={"marginTop": "8px"})

    action_fa = {"advance": "پیشروی", "reject": "بازگشت", "skip": "رد (اختیاری)"}
    lines = []
    for h in history[:3]:
        origin = h["from_label"] or "شروع"
        line = f"{action_fa.get(h['action'], h['action'])}: {origin} ← {h['to_label']}"
        if h["actor"]:
            line += f" — {h['actor']}"
        lines.append(html.Div(line, style={"fontSize": "11px", "color": TEXT_MUTED}))
        if h["note"]:
            lines.append(html.Div(f"« {h['note']} »", style={"fontSize": "11px", "color": TEXT_SECONDARY, "marginBottom": "4px"}))
    return html.Div(
        style={"marginTop": "10px", "borderTop": f"1px dashed {BORDER}", "paddingTop": "8px"},
        children=[
            toggle,
            html.Div(lines, style={"marginTop": "6px"}),
            html.Div(
                [
                    dcc.Input(
                        id={"type": "instance-note-input", "instance_id": instance_id},
                        type="text",
                        placeholder="یادداشتی برای آخرین تغییر بنویسید…",
                        style={"flex": "1", "minWidth": "0", "height": "26px", "fontSize": "11px"},
                    ),
                    html.Button(
                        "افزودن یادداشت",
                        id={"type": "instance-note-save-btn", "instance_id": instance_id},
                        n_clicks=0,
                        className="fpa-btn-quiet",
                        style={"border": f"1px solid {BORDER}", "fontSize": "11px", "padding": "2px 10px", "flexShrink": "0"},
                    ),
                ],
                style={"display": "flex", "gap": "6px", "marginTop": "6px"},
            ),
        ],
    )


def build_instance_list(
    instances: list[dict],
    steps: list[dict],
    editing_instance_id: int | None = None,
    history_by_instance: dict[int, list[dict]] | None = None,
    expanded_history_instance_id: int | None = None,
):
    # `instances` is always exactly one row once a workflow is selected -
    # callbacks.py always fetches it through workflow.get_or_create_instance,
    # which creates it silently the first time (see that function's
    # docstring). Only reachable empty here when no workflow is selected at
    # all (e.g. the database has zero versions - can't happen in practice,
    # since app.serve_layout/switch_module always create one), so this is a
    # defensive fallback, not a real "go create one" prompt anymore.
    if not instances:
        return html.Div(
            "گردش‌کاری انتخاب نشده.",
            style={"color": TEXT_MUTED, "fontSize": "13px"},
        )
    history_by_instance = history_by_instance or {}
    return [
        build_instance_row(
            inst,
            steps,
            editing_instance_id=editing_instance_id,
            history=history_by_instance.get(inst["instance_id"]),
            expanded_history_instance_id=expanded_history_instance_id,
        )
        for inst in instances
    ]


def canvas_render_token(version: dict | None) -> str:
    """A value that changes any time the canvas needs a client-side resync -
    on a version switch (version_id changes) AND after Save on the *same*
    version (step_ids all get replaced by save_steps, so updated_at moving
    forward must also count as "changed", or the drag-and-drop JS would
    keep using now-stale step keys after a save)."""
    if not version:
        return "none"
    return f"{version['version_id']}::{version['updated_at']}"


def steps_json(steps: list[dict]) -> str:
    """The JSON string dragdrop.js parses out of #fpa-steps-payload -
    shared by the initial render and by callbacks.py so both stay identical."""
    return json.dumps(
        [
            {
                "step_id": s["step_id"],
                "role_id": s["role_id"],
                "role_name": s["role_name"],
                "color_hex": s["color_hex"],
                "label": s["label"],
            }
            for s in steps
        ]
    )


def steps_store_payload(steps: list[dict]) -> list[dict]:
    """The shape workflow-steps-store's data always has, whether it was just
    set here (server render / after a save) or by dragdrop.js's own
    pushToStore(). `key` = "s<step_id>" is what lets workflow.save_steps
    recognize "this is the same step as before" on the next Save and UPDATE
    it in place instead of recreating it - skip it here and every step
    looks brand-new next Save, silently wiping owner/duty/template/etc for
    steps nobody actually touched.
    """
    return [{"role_id": s["role_id"], "label": s["label"], "key": f"s{s['step_id']}"} for s in steps]


def build_steps_payload(version: dict | None):
    """A hidden element carrying the authoritative step list as JSON.

    Why not just render #fpa-canvas's children straight from a Dash
    callback: after the drag-and-drop JS has mutated #fpa-canvas's real DOM
    directly (adding/reordering/removing chips outside of React), Dash's
    virtual DOM no longer matches the actual DOM there - a later callback
    writing to that same node's children crashes React's reconciliation
    ("removeChild... not a child of this node"). Splitting ownership fixes
    it: Dash only ever touches this invisible payload node, and
    dragdrop.js's MutationObserver is the *only* thing that ever writes to
    #fpa-canvas, so the two never contend for the same DOM.
    """
    steps = version["steps"] if version else []
    return html.Div(
        id="fpa-steps-payload",
        style={"display": "none"},
        **{
            "data-version-id": canvas_render_token(version),
            "data-steps": steps_json(steps),
        },
    )


def build_canvas_dropzone(version: dict | None):
    steps = version["steps"] if version else []
    return html.Div(
        id="fpa-canvas-dropzone",
        className="fpa-canvas-dropzone",
        # The step sequence reads as a left-to-right flow (like any
        # flowchart/timeline) even in an otherwise-RTL Persian page - see
        # the same reasoning on .fpa-track in build_instance_row.
        style={"direction": "ltr"},
        children=[
            build_steps_payload(version),
            html.Div(
                style={"display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "6px", "width": "100%"},
                children=[
                    # START/END are pure decoration - never touched by Dash
                    # again after this first render, and never touched by
                    # dragdrop.js either (it only ever repaints #fpa-canvas),
                    # so they can't conflict with either side's ownership.
                    html.Div("شروع", className="fpa-endpoint"),
                    html.Span("→", className="fpa-arrow"),
                    html.Div(id="fpa-canvas", className="fpa-canvas", children=build_canvas_children(steps)),
                    html.Span("→", className="fpa-arrow"),
                    html.Div("پایان", className="fpa-endpoint"),
                ],
            ),
        ],
    )


def build_step_details_list(steps: list[dict]):
    """A compact row of small numbered, role-colored badges - one per
    *saved* step (steps here always have a real step_id - see
    workflow.get_version), each opening build_step_detail_modal for that
    step. Deliberately not a second full list repeating what the canvas
    above already shows (role, order, label) - only the *presence* of
    detail is signaled here (a filled ring), the detail itself lives in the
    modal. A step still only on the canvas, not yet saved, has no stable
    step_id to hang detail on - see build_step_detail_modal's docstring -
    so nothing appears here for it until at least one Save.
    """
    if not steps:
        return html.Div(
            "برای افزودن جزئیات (مالک، وظیفه، ورودی/خروجی، فایل الگو)، اول «ذخیره‌ی تغییرات» را بزنید.",
            style={"color": TEXT_MUTED, "fontSize": "11.5px", "marginTop": "12px"},
        )
    badges = []
    for i, s in enumerate(steps):
        has_detail = bool(
            s["owner"]
            or s["duty"]
            or s["input_desc"]
            or s["output_desc"]
            or s["acceptance_criteria"]
            or s["sla_days"]
            or s["is_optional"]
            or s["template_original_name"]
        )
        badges.append(
            html.Button(
                str(i + 1),
                id={"type": "step-detail-btn", "step_id": s["step_id"]},
                n_clicks=0,
                className="fpa-step-badge" + (" fpa-step-badge-filled" if has_detail else ""),
                style={"background": s["color_hex"]},
                title=s["label"] + (" — جزئیات ثبت شده (کلیک برای ویرایش)" if has_detail else " — افزودن جزئیات"),
            )
        )
    return html.Div(
        style={"display": "flex", "alignItems": "center", "gap": "10px", "flexWrap": "wrap", "marginTop": "12px"},
        children=[
            html.Span("جزئیات هر مرحله:", style={"color": TEXT_MUTED, "fontSize": "11.5px", "flexShrink": "0"}),
            html.Div(badges, style={"display": "flex", "gap": "6px", "direction": "ltr"}),
        ],
    )


def step_detail_backdrop_style(hidden: bool) -> dict:
    return {
        "position": "fixed",
        "inset": "0",
        "background": "var(--fpa-overlay-backdrop)",
        "display": "none" if hidden else "flex",
        "alignItems": "center",
        "justifyContent": "center",
        "zIndex": "1000",
        "padding": "20px",
    }


def step_template_status(step: dict | None):
    """(current_text, actions_style) for the modal's template area - used
    both when opening the modal and after an upload/clear. The download/
    clear buttons are always present in the DOM (see
    build_step_detail_modal) and only ever have their *style* toggled here,
    never added/removed - the same "static shell" reasoning TOUR_STEPS'
    modal docstring explains: Dash's client-side render validates that a
    callback Input's id exists in the *first* layout it ever saw, so an id
    born only later, inside a callback-injected subtree, fails that check.
    """
    if step and step.get("template_original_name"):
        return f"📎 {step['template_original_name']}", {"display": "flex", "gap": "8px", "marginTop": "8px"}
    return "فایلی بارگذاری نشده", {"display": "none", "gap": "8px", "marginTop": "8px"}


def build_step_detail_modal():
    field_label_style = {"color": TEXT_SECONDARY, "fontSize": "12px", "display": "block", "marginBottom": "4px", "marginTop": "10px"}
    field_style = {"width": "100%"}
    current_text, actions_style = step_template_status(None)
    return html.Div(
        id="step-detail-backdrop",
        style=step_detail_backdrop_style(hidden=True),
        children=html.Div(
            style={
                **CARD_STYLE,
                "width": "min(480px, 92vw)",
                "maxHeight": "88vh",
                "overflowY": "auto",
                "position": "relative",
                "boxShadow": "0 20px 48px var(--fpa-shadow-lg)",
            },
            children=[
                html.Button(
                    "×",
                    id="step-detail-close-btn",
                    n_clicks=0,
                    title="بستن",
                    className="fpa-btn-quiet",
                    style={
                        "position": "absolute",
                        "top": "10px",
                        "insetInlineEnd": "10px",
                        "color": TEXT_MUTED,
                        "fontSize": "18px",
                        "padding": "2px 8px",
                        "lineHeight": "1",
                    },
                ),
                html.Div(id="step-detail-title", style={"fontWeight": "700", "fontSize": "16px", "marginBottom": "4px"}),
                html.Div("جزئیات این مرحله - همه‌ی فیلدها اختیاری‌اند.", style={"color": TEXT_MUTED, "fontSize": "11.5px"}),
                html.Label("مالک", style=field_label_style),
                dcc.Input(id="step-detail-owner-input", type="text", style=field_style),
                html.Label("وظیفه", style=field_label_style),
                dcc.Textarea(id="step-detail-duty-input", style={**field_style, "minHeight": "50px"}),
                html.Label("ورودی", style=field_label_style),
                dcc.Textarea(id="step-detail-input-input", style={**field_style, "minHeight": "50px"}),
                html.Label("خروجی", style=field_label_style),
                dcc.Textarea(id="step-detail-output-input", style={**field_style, "minHeight": "50px"}),
                html.Label("شرایط پذیرش خروجی", style=field_label_style),
                dcc.Textarea(id="step-detail-acceptance-criteria-input", style={**field_style, "minHeight": "50px"}),
                html.Label("موضوع پیام اعلان", style=field_label_style),
                dcc.Input(
                    id="step-detail-notification-subject-input",
                    type="text",
                    placeholder="خالی = موضوع خودکار (نام فرایند و مرحله)",
                    style=field_style,
                ),
                html.Div(
                    style={"display": "flex", "gap": "16px", "marginTop": "10px", "alignItems": "flex-end", "flexWrap": "wrap"},
                    children=[
                        html.Div(
                            [
                                html.Label("مهلت (روز)", style={**field_label_style, "marginTop": "0"}),
                                dcc.Input(id="step-detail-sla-input", type="number", min=1, style={"width": "110px"}),
                            ]
                        ),
                        dcc.Checklist(
                            id="step-detail-optional-checkbox",
                            options=[{"label": " این مرحله اختیاری است (قابل رد‌کردن)", "value": "optional"}],
                            value=[],
                            style={"fontSize": "12.5px"},
                        ),
                    ],
                ),
                html.Label("فایل الگو (Template)", style=field_label_style),
                html.Div(id="step-detail-template-current", children=current_text, style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "6px"}),
                dcc.Upload(
                    id="step-detail-template-upload",
                    children=html.Div("فایل را اینجا رها کنید یا برای انتخاب کلیک کنید", style={"fontSize": "12px", "textAlign": "center"}),
                    className="fpa-upload-zone",
                ),
                html.Div(
                    id="step-detail-template-actions",
                    style=actions_style,
                    children=[
                        html.Button(
                            "دانلود",
                            id="step-detail-template-download-btn",
                            n_clicks=0,
                            className="fpa-btn-quiet",
                            style={"border": f"1px solid {BORDER}", "fontSize": "12px"},
                        ),
                        html.Button(
                            "حذف فایل",
                            id="step-detail-template-clear-btn",
                            n_clicks=0,
                            className="fpa-btn-danger",
                            style={"fontSize": "12px"},
                        ),
                    ],
                ),
                html.Div(
                    html.Button("ذخیره‌ی جزئیات", id="step-detail-save-btn", n_clicks=0, style={"width": "100%"}),
                    style={"marginTop": "18px"},
                ),
                html.Div(id="step-detail-save-status", style={"color": TEXT_SECONDARY, "fontSize": "11.5px", "marginTop": "6px", "textAlign": "center"}),
                dcc.Download(id="step-detail-download"),
            ],
        ),
    )


def build_status_summary(summary: list[dict]):
    """Per-step pending/overdue counts (workflow.step_status_summary) for
    the currently-selected version - doubles as a lightweight "what needs
    attention" view (who's assigned, how many are stuck) and a "how's this
    process performing" glance, without needing a whole separate reporting
    module for it.
    """
    if not summary:
        return html.Div("برای این نسخه هنوز مرحله‌ای تعریف نشده.", style={"color": TEXT_MUTED, "fontSize": "12.5px"})
    tiles = []
    for row in summary:
        tile_children = [
            html.Div(
                [
                    html.Span(
                        style={
                            "display": "inline-block",
                            "width": "9px",
                            "height": "9px",
                            "borderRadius": "50%",
                            "background": row["color_hex"],
                            "marginLeft": "6px",
                        }
                    ),
                    html.Span(row["label"], style={"fontWeight": "700", "fontSize": "13px"}),
                ]
            ),
            html.Div(f"{row['pending_count']} در انتظار", style={"fontSize": "12px", "color": TEXT_SECONDARY, "marginTop": "6px"}),
        ]
        if row["overdue_count"]:
            tile_children.append(
                html.Div(f"⚠ {row['overdue_count']} معطل‌مانده", style={"fontSize": "11.5px", "color": CRITICAL_COLOR, "marginTop": "2px", "fontWeight": "700"})
            )
        if row["assignee_name"]:
            tile_children.append(html.Div(f"مسئول: {row['assignee_name']}", style={"fontSize": "11px", "color": TEXT_MUTED, "marginTop": "2px"}))
        tiles.append(
            html.Div(
                style={
                    "background": "var(--fpa-surface-2)",
                    "border": f"1px solid {BORDER}",
                    "borderRadius": "10px",
                    "padding": "12px 14px",
                    "minWidth": "150px",
                    "flex": "1",
                },
                children=tile_children,
            )
        )
    return html.Div(tiles, style={"display": "flex", "gap": "10px", "flexWrap": "wrap"})


def workflow_tab_button_class(tab_id: str, active_tab: str) -> str:
    return "fpa-workflow-tab fpa-workflow-tab-active" if tab_id == active_tab else "fpa-workflow-tab"


def workflow_tab_container_style(visible: bool) -> dict:
    return {"display": "block" if visible else "none"}


def build_workflow_tab_bar(active: str = "design"):
    return html.Div(
        className="fpa-workflow-tab-bar",
        children=[
            html.Button("طراحی", id="workflow-tab-design-btn", n_clicks=0, className=workflow_tab_button_class("design", active)),
            html.Button(
                "نمونه‌های در حال اجرا",
                id="workflow-tab-instances-btn",
                n_clicks=0,
                className=workflow_tab_button_class("instances", active),
            ),
        ],
    )


def build_designer_page(
    roles: list[dict],
    versions: list[dict],
    selected_version: dict,
    instances: list[dict],
    status_summary: list[dict] | None = None,
    history_by_instance: dict[int, list[dict]] | None = None,
    expanded_history_instance_id: int | None = None,
):
    # Two tabs, not one long scroll: "طراحی" (roles/canvas/step-detail) is
    # what you touch while building a template, "نمونه‌های در حال اجرا" is
    # what you touch while tracking real cycles - these are different
    # moments of use, so showing both at once (the original design) was
    # forcing everyone to scroll past whichever half they didn't need. Both
    # tab bodies are *always* rendered (only `style.display` toggles) -
    # never conditionally swapped out - specifically so every id inside
    # them still exists in the very first layout Dash's client-side
    # validator ever sees (see build_step_detail_modal's docstring on why
    # that matters for a callback Input to be valid at all).
    steps = selected_version["steps"] if selected_version else []
    return html.Div(
        [
            html.Div(id="version-bar-container", children=build_version_bar(versions, selected_version)),
            build_workflow_tab_bar(active="design"),
            html.Div(
                id="workflow-design-tab",
                style=workflow_tab_container_style(visible=True),
                children=[
                    html.Div(
                        style={"display": "flex", "gap": "20px", "alignItems": "flex-start", "flexWrap": "wrap"},
                        children=[
                            html.Div(
                                style={**CARD_STYLE, "width": "220px", "flexShrink": "0"},
                                children=[
                                    html.Div("نقش‌ها", style={"fontWeight": "600", "marginBottom": "4px"}),
                                    html.Div(
                                        "یک نقش را به بوم بکشید تا یک مرحله اضافه شود.",
                                        style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px"},
                                    ),
                                    html.Div(build_role_palette(roles), id="role-palette"),
                                    html.Div(
                                        style={"borderTop": f"1px solid {BORDER}", "marginTop": "16px", "paddingTop": "14px"},
                                        children=[
                                            html.Label("+ افزودن نقش", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
                                            dcc.Input(
                                                id="new-role-name",
                                                type="text",
                                                placeholder="نام نقش",
                                                style={"width": "100%", "height": "32px", "marginTop": "6px", "marginBottom": "8px"},
                                            ),
                                            html.Button("افزودن", id="add-role-btn", n_clicks=0, style={"width": "100%"}),
                                            html.Div(id="add-role-status", style={"color": TEXT_SECONDARY, "fontSize": "11.5px", "marginTop": "6px"}),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(
                                style={**CARD_STYLE, "flex": "1", "minWidth": "420px"},
                                children=[
                                    html.Div(
                                        style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "4px"},
                                        children=[
                                            html.Div("مراحل گردش‌کار", style={"fontWeight": "600"}),
                                            html.Div(
                                                [
                                                    html.Button(
                                                        "↩",
                                                        id="fpa-undo-btn",
                                                        # No Dash callback owns this button on
                                                        # purpose - dragdrop.js's own click
                                                        # listener handles it (see
                                                        # pushHistory/__fpaHistory there), the
                                                        # same "vanilla JS, not Dash" ownership
                                                        # as everything else on this canvas.
                                                        # n_clicks is never read.
                                                        n_clicks=0,
                                                        className="fpa-icon-btn",
                                                        title="آخرین تغییر روی بوم را واگرد کن (قبل از ذخیره)",
                                                    ),
                                                    html.Button("ذخیره‌ی تغییرات", id="save-steps-btn", n_clicks=0),
                                                ],
                                                style={"display": "flex", "gap": "8px"},
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        "یک نقش را از پنل نقش‌ها به این بوم بکشید تا مرحله‌ای اضافه شود. برای تغییر ترتیب، یک مرحله‌ی موجود را بکشید؛ برای حذف، آن را به سطل زباله بکشید.",
                                        style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px"},
                                    ),
                                    build_canvas_dropzone(selected_version),
                                    html.Div(
                                        "🗑  برای حذف مرحله اینجا رها کنید",
                                        id="fpa-trash-zone",
                                        className="fpa-trash-zone",
                                    ),
                                    html.Div(id="step-details-list", children=build_step_details_list(steps)),
                                    html.Div(id="save-steps-status", style={"color": TEXT_SECONDARY, "fontSize": "12px", "marginTop": "10px"}),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                id="workflow-instances-tab",
                style=workflow_tab_container_style(visible=False),
                children=[
                    html.Div(
                        style={**CARD_STYLE, "marginBottom": "20px"},
                        children=[
                            html.Div("خلاصه‌ی وضعیت — این نسخه", style={"fontWeight": "600", "marginBottom": "10px"}),
                            html.Div(id="status-summary-content", children=build_status_summary(status_summary or [])),
                        ],
                    ),
                    html.Div(
                        style={**CARD_STYLE},
                        children=[
                            html.Div("روند اجرای این گردش‌کار", style={"fontWeight": "600", "marginBottom": "4px"}),
                            html.Div(
                                # Each workflow tracks exactly one run of itself now - no
                                # separate "create an instance" step, see
                                # workflow.get_or_create_instance. To run two real cycles of
                                # the same design in parallel (e.g. two budget years), make a
                                # second workflow (version) for the second one - each has its
                                # own independent progress.
                                "برای مشخص‌کردن مرحله‌ی فعلی این گردش‌کار، روی یکی از مراحل زیر کلیک کنید.",
                                style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px"},
                            ),
                            html.Div(
                                id="instance-list",
                                children=build_instance_list(
                                    instances,
                                    steps,
                                    history_by_instance=history_by_instance,
                                    expanded_history_instance_id=expanded_history_instance_id,
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        ]
    )


# First-run onboarding tour - a short, skippable walkthrough of the app's
# main areas. "Seen" state lives in tour-seen-store (dcc.Store,
# storage_type="local" - browser localStorage), so it shows automatically
# once per browser, not once per page load; callbacks.py's dismiss_tour and
# render_tour wire the buttons referenced by id below.
TOUR_STEPS = [
    {
        "title": "به طراح گردش‌کار بودجه‌ریزی خوش آمدید",
        "body": "با این ابزار می‌توانید مراحل گردش تصویب بودجه را طراحی کنید و نمونه‌های واقعی آن را دنبال کنید. این چند مرحله‌ی کوتاه، بخش‌های اصلی صفحه را نشان می‌دهد.",
    },
    {
        "title": "گردش‌کارها",
        "body": "در کارت سمت راست یک گردش‌کار جدید بسازید؛ در کارت سمت چپ یکی از گردش‌کارهای موجود را انتخاب کنید و بین آن‌ها سوییچ کنید.",
    },
    {
        "title": "نقش‌ها",
        "body": "نقش‌های موجود را از این پنل به بوم طراحی بکشید تا به‌عنوان یک مرحله اضافه شوند. برای تغییر نام یک نقش، روی نامش کلیک کنید. نقش تازه هم می‌توانید از پایین همین پنل اضافه کنید.",
    },
    {
        "title": "بوم طراحی گردش‌کار",
        "body": "ترتیب مراحل را با کشیدن‌شان تغییر دهید، و برای حذف یک مرحله، آن را به سطل زباله زیر بوم بکشید. پس از هر تغییر، «ذخیره‌ی تغییرات» را بزنید.",
    },
    {
        "title": "روند اجرا",
        "body": "هر گردش‌کار، روند اجرای خودش را دارد - کافی است روی مراحل تب «نمونه‌های در حال اجرا» کلیک کنید تا مرحله‌ی فعلی‌اش را مشخص کنید؛ نیازی به ساختن جداگانه‌ی چیزی نیست.",
    },
]


TOUR_PREV_STYLE_BASE = {"border": f"1px solid {BORDER}", "color": TEXT_SECONDARY}


def tour_backdrop_style(hidden: bool) -> dict:
    return {
        "position": "fixed",
        "inset": "0",
        "background": "var(--fpa-overlay-backdrop)",
        "display": "none" if hidden else "flex",
        "alignItems": "center",
        "justifyContent": "center",
        "zIndex": "1000",
    }


def tour_nav_style(base: dict, visible: bool) -> dict:
    return {**base, "display": "inline-block" if visible else "none"}


def build_tour_dots(step: int):
    return [
        html.Span(
            style={
                "display": "inline-block",
                "width": "7px",
                "height": "7px",
                "borderRadius": "50%",
                "margin": "0 3px",
                "background": ACCENT if i == step else BORDER,
            }
        )
        for i in range(len(TOUR_STEPS))
    ]


def build_tour_overlay():
    """The tour's full markup, rendered once as part of the very first page
    load and never removed from the DOM afterwards - callbacks.render_tour
    only ever toggles style/children on these same, permanent ids.

    This shape (as opposed to a callback swapping this whole subtree in and
    out of an empty placeholder) is required, not just tidier: Dash's
    client-side renderer validates that every callback Input's id exists
    *somewhere* in the current layout, and it only ever sees the layout
    produced by the first render - an id that is born later, only once a
    callback injects it, fails that check with "A nonexistent object was
    used in an Input of a Dash callback" before the callback wiring it up
    ever gets a chance to run.
    """
    return html.Div(
        id="tour-backdrop",
        style=tour_backdrop_style(hidden=True),
        children=html.Div(
            style={
                **CARD_STYLE,
                "width": "min(420px, 90vw)",
                "position": "relative",
                "boxShadow": "0 20px 48px var(--fpa-shadow-lg)",
            },
            children=[
                html.Button(
                    "×",
                    id="tour-close-btn",
                    n_clicks=0,
                    title="بستن راهنما",
                    className="fpa-btn-quiet",
                    style={
                        "position": "absolute",
                        "top": "10px",
                        "insetInlineEnd": "10px",
                        "color": TEXT_MUTED,
                        "fontSize": "18px",
                        "padding": "2px 8px",
                        "lineHeight": "1",
                    },
                ),
                html.Div(id="tour-step-counter", style={"color": TEXT_MUTED, "fontSize": "11.5px", "marginBottom": "10px"}),
                html.Div(id="tour-step-title", style={"fontWeight": "700", "fontSize": "17px", "marginBottom": "8px"}),
                html.Div(id="tour-step-body", style={"color": TEXT_SECONDARY, "fontSize": "13.5px", "lineHeight": "1.7"}),
                html.Div(id="tour-step-dots", style={"marginTop": "18px", "marginBottom": "6px"}),
                html.Div(
                    [
                        html.Button(
                            "رد کردن آموزش",
                            id="tour-skip-btn",
                            n_clicks=0,
                            className="fpa-btn-quiet",
                            style={"color": TEXT_MUTED, "padding": "8px 4px"},
                        ),
                        html.Div(style={"flex": "1"}),
                        html.Button("قبلی", id="tour-prev-btn", n_clicks=0, className="fpa-btn-quiet", style=TOUR_PREV_STYLE_BASE),
                        html.Button("بعدی", id="tour-next-btn", n_clicks=0),
                        html.Button("شروع کنید", id="tour-finish-btn", n_clicks=0),
                    ],
                    style={"display": "flex", "alignItems": "center", "gap": "8px", "marginTop": "10px"},
                ),
            ],
        ),
    )


# Top-level modules the sidebar switches between (callbacks.switch_module).
# Only "workflow" has real content today - the rest are scaffolded now so
# the app's shape is right, and get filled in later (per the user's own
# framing: "بعداً به این ماژول‌ها اضافه هم می‌شه").
MODULES = [
    {"id": "workflow", "icon": "🔁", "label": "طراح گردش‌کار"},
    {"id": "statements", "icon": "📊", "label": "صورت‌های مالی سه‌گانه"},
    {"id": "actual-budget", "icon": "⚖️", "label": "واقعی و بودجه"},
    {"id": "admin", "icon": "⚙️", "label": "پنل مدیریت"},
]

PLACEHOLDER_MODULES = {
    "statements": (
        "صورت‌های مالی سه‌گانه",
        "سود و زیان، ترازنامه، و صورت جریان نقدی به‌صورت واقعی - این بخش به‌زودی تکمیل می‌شود.",
    ),
    "actual-budget": (
        "واقعی و بودجه",
        "مقایسه‌ی ارقام واقعی با بودجه و تحلیل انحراف - این بخش به‌زودی تکمیل می‌شود.",
    ),
    "admin": (
        "پنل مدیریت",
        "مدیریت کاربران، دسترسی‌ها و تنظیمات - این بخش به‌زودی تکمیل می‌شود.",
    ),
}


def sidebar_button_class(module_id: str, active_module: str) -> str:
    return "fpa-sidebar-btn fpa-sidebar-btn-active" if module_id == active_module else "fpa-sidebar-btn"


def build_sidebar(active_module: str = "workflow"):
    return html.Div(
        className="fpa-sidebar",
        children=[
            html.Div(
                className="fpa-sidebar-header",
                children=[
                    html.Button(
                        "🌙",
                        id="theme-toggle-btn",
                        n_clicks=0,
                        className="fpa-theme-toggle",
                        title="تغییر تم روشن/تاریک",
                    ),
                    html.Div(
                        [
                            html.Div("FP-A", style={"fontSize": "18px", "fontWeight": "700"}),
                            html.Div(
                                "طراح گردش‌کار بودجه‌ریزی",
                                style={"fontSize": "11.5px", "opacity": "0.75", "marginTop": "1px"},
                            ),
                        ]
                    ),
                ],
            ),
            html.Div(
                className="fpa-sidebar-nav",
                children=[
                    html.Button(
                        [html.Span(m["icon"], className="fpa-sidebar-icon"), html.Span(m["label"])],
                        id={"type": "module-nav-btn", "module": m["id"]},
                        n_clicks=0,
                        className=sidebar_button_class(m["id"], active_module),
                    )
                    for m in MODULES
                ],
            ),
        ],
    )


def build_module_header(module_id: str):
    module = next((m for m in MODULES if m["id"] == module_id), MODULES[0])
    return html.Div(
        [html.Span(module["icon"]), html.Span(module["label"])],
        style={"display": "flex", "alignItems": "center", "gap": "10px", "fontSize": "18px", "fontWeight": "700", "marginBottom": "20px"},
    )


def build_placeholder_module(module_id: str):
    title, description = PLACEHOLDER_MODULES[module_id]
    return html.Div(
        style={**CARD_STYLE, "textAlign": "center", "padding": "70px 24px"},
        children=[
            html.Div("🚧", style={"fontSize": "38px", "marginBottom": "14px"}),
            html.Div(title, style={"fontWeight": "700", "fontSize": "16px", "marginBottom": "8px"}),
            html.Div(description, style={"color": TEXT_MUTED, "fontSize": "13.5px", "maxWidth": "440px", "margin": "0 auto"}),
        ],
    )


def build_module_content(
    module_id: str,
    roles,
    versions,
    selected_version,
    instances,
    status_summary: list[dict] | None = None,
    history_by_instance: dict[int, list[dict]] | None = None,
    expanded_history_instance_id: int | None = None,
):
    if module_id in PLACEHOLDER_MODULES:
        return build_placeholder_module(module_id)
    return build_designer_page(
        roles,
        versions,
        selected_version,
        instances,
        status_summary,
        history_by_instance,
        expanded_history_instance_id,
    )


def build_shell(
    roles,
    versions,
    selected_version,
    instances,
    active_module: str = "workflow",
    status_summary: list[dict] | None = None,
    history_by_instance: dict[int, list[dict]] | None = None,
    expanded_history_instance_id: int | None = None,
):
    return html.Div(
        id="fpa-app-root",
        dir="rtl",
        style={
            "background": PAGE,
            "minHeight": "100vh",
            "color": TEXT_PRIMARY,
            "direction": "rtl",
            "fontFamily": 'Tahoma, "Segoe UI", system-ui, sans-serif',
            "display": "flex",
            "alignItems": "flex-start",
        },
        children=[
            # Persisted per-browser (storage_type="local"), like
            # tour-seen-store below - callbacks.apply_theme sets it as
            # data-theme on <html> (not on this div: some Dash-rendered
            # bits, like dropdown popups and this ConfirmDialog, portal
            # outside #fpa-app-root in the real DOM, and CSS custom
            # properties only cascade to where the attribute actually sits).
            dcc.Store(id="theme-store", storage_type="local", data="dark"),
            # Which of MODULES is on screen - callbacks.switch_module writes
            # it, build_sidebar/build_module_header read it.
            dcc.Store(id="active-module", data=active_module),
            build_sidebar(active_module),
            html.Div(
                style={"flex": "1", "minWidth": "0", "padding": "28px 36px 60px"},
                children=[
                    dcc.Store(
                        id="workflow-steps-store",
                        data=steps_store_payload(selected_version["steps"] if selected_version else []),
                    ),
                    # Which role, if any, is currently showing its inline
                    # rename form in the roles panel - see
                    # build_role_palette/edit_role.
                    dcc.Store(id="editing-role-id", data=None),
                    # Same idea, for one instance's name - see
                    # build_instance_row/callbacks.edit_instance_name. (No
                    # delete-instance confirm/store here anymore - a
                    # workflow's progress tracker is auto-managed 1:1 with
                    # its version now, not a separately deletable thing; see
                    # workflow.get_or_create_instance.)
                    dcc.Store(id="editing-instance-id", data=None),
                    # "Confirm, then delete" shape for a role - a role still
                    # referenced by any workflow_step (any version, draft or
                    # active) can't actually be deleted (FK on
                    # workflow_step.role_id, see sql/schema.sql), so
                    # confirm_delete_role checks workflow.role_step_usage_count
                    # first and reports that instead of attempting - and
                    # failing - the DELETE. See build_role_palette/
                    # callbacks.ask_delete_role/confirm_delete_role.
                    dcc.ConfirmDialog(id="delete-role-confirm", message=""),
                    dcc.Store(id="pending-delete-role-id", data=None),
                    # Which step's detail editor (owner/duty/input/output/
                    # acceptance_criteria/notification_subject/template) is currently open - see
                    # build_step_detail_modal/callbacks.open_or_close_step_detail.
                    dcc.Store(id="editing-step-detail-id", data=None),
                    build_step_detail_modal(),
                    # dcc.Upload fires its "contents" Input more than once
                    # for a single real file pick (confirmed live) - these
                    # dedupe by content hash so one upload can't get
                    # processed 2-3 times. See callbacks.import_version/
                    # upload_step_template.
                    dcc.Store(id="last-import-hash", data=None),
                    dcc.Store(id="last-template-upload-hash", data=None),
                    # Which instance's history panel (if any) is expanded -
                    # see build_instance_history/callbacks.toggle_instance_history.
                    # At most one open at a time, so this is a scalar, not a set.
                    dcc.Store(id="expanded-history-instance-id", data=expanded_history_instance_id),
                    html.Div(id="module-header", children=build_module_header(active_module)),
                    html.Div(
                        id="page-content",
                        children=build_module_content(
                            active_module,
                            roles,
                            versions,
                            selected_version,
                            instances,
                            status_summary=status_summary,
                            history_by_instance=history_by_instance,
                            expanded_history_instance_id=expanded_history_instance_id,
                        ),
                    ),
                    # Ticks in the background for as long as the page is
                    # open, so the read-only mirror file (db.sync_mirror)
                    # keeps refreshing without needing any user interaction
                    # - see callbacks.sync_mirror_tick.
                    dcc.Interval(id="mirror-sync-interval", interval=5000, n_intervals=0),
                    html.Div(id="mirror-sync-status", style={"color": TEXT_MUTED, "fontSize": "11px", "marginTop": "18px"}),
                ],
            ),
            # First-run onboarding tour (see TOUR_STEPS/build_tour_overlay
            # above and callbacks.render_tour/dismiss_tour) - tour-seen-store
            # is storage_type="local" so it only ever auto-shows once per
            # browser; tour-overlay-root starts empty and is filled in by
            # render_tour on page load if this browser hasn't seen it yet.
            dcc.Store(id="tour-seen-store", storage_type="local", data=False),
            dcc.Store(id="tour-step-store", data=0),
            build_tour_overlay(),
        ],
    )

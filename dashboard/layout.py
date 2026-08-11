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
    chips = []
    for role in roles:
        if role["role_id"] == editing_role_id:
            chips.append(
                html.Div(
                    className="fpa-role-chip fpa-role-chip-editing",
                    style={"background": role["color_hex"]},
                    children=[
                        dcc.Input(
                            id={"type": "role-name-input", "role_id": role["role_id"]},
                            value=role["role_name"],
                            type="text",
                            autoFocus=True,
                            style={
                                "flex": "1",
                                "minWidth": "0",
                                "background": "rgba(255,255,255,0.15)",
                                "border": "1px solid rgba(255,255,255,0.4)",
                                "borderRadius": "6px",
                                "color": "#ffffff",
                                "padding": "4px 8px",
                                "fontSize": "13px",
                            },
                        ),
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
                )
            )
        else:
            chips.append(
                html.Div(
                    className="fpa-role-chip",
                    draggable="true",
                    style={"background": role["color_hex"]},
                    **{
                        "data-role-id": role["role_id"],
                        "data-role-name": role["role_name"],
                        "data-color": role["color_hex"],
                    },
                    children=[
                        html.Span("⠿", className="fpa-drag-handle"),
                        html.Span(
                            role["role_name"],
                            id={"type": "role-chip-label", "role_id": role["role_id"]},
                            n_clicks=0,
                            className="fpa-role-chip-label",
                            title="برای ویرایش نام کلیک کنید",
                        ),
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
                style={"background": step["color_hex"]},
                **{
                    "data-key": f"s{step['step_id']}",
                    "data-role-id": step["role_id"],
                    "data-role-name": step["role_name"],
                    "data-color": step["color_hex"],
                    "data-label": step["label"],
                },
                children=[
                    html.Span(str(i + 1), className="fpa-step-index"),
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
    return html.Div(
        style={**CARD_STYLE, "display": "flex", "gap": "14px", "alignItems": "flex-end", "flexWrap": "wrap", "marginBottom": "20px"},
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
                [
                    html.Label("نام نسخه‌ی جدید", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
                    dcc.Input(
                        id="new-version-name",
                        type="text",
                        placeholder="مثلاً «تصویب بودجه‌ی ۱۴۰۵»",
                        style={"width": "240px", "height": "34px"},
                    ),
                ]
            ),
            html.Button("+ نسخه‌ی جدید", id="create-version-btn", n_clicks=0),
            html.Button("فعال‌سازی", id="activate-version-btn", n_clicks=0),
            html.Div(id="version-status-badge", children=build_status_badge(selected_version["status"]) if selected_version else ""),
            html.Div(id="version-action-status", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
        ],
    )


def build_instance_row(instance: dict, steps: list[dict], editing_instance_id: int | None = None):
    current_step_id = instance["current_step_id"]
    current_index = None
    for i, s in enumerate(steps):
        if s["step_id"] == current_step_id:
            current_index = i
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

    return html.Div(
        className="fpa-instance-row",
        children=[
            html.Div(
                [
                    name_area,
                    html.Button(
                        "🗑",
                        id={"type": "delete-instance-btn", "instance_id": instance["instance_id"]},
                        n_clicks=0,
                        className="fpa-btn-danger",
                        style={"padding": "3px 10px", "fontSize": "12px"},
                        title="حذف این نمونه",
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "gap": "10px", "marginBottom": "4px"},
            ),
            banner,
            # This track mirrors the canvas's step sequence, so it stays
            # left-to-right too, same reasoning as build_canvas_dropzone.
            html.Div(track_children, className="fpa-track", style={"direction": "ltr"}),
        ],
    )


def build_instance_list(instances: list[dict], steps: list[dict], editing_instance_id: int | None = None):
    if not instances:
        return html.Div(
            "هنوز نمونه‌ای برای این نسخه ایجاد نشده — برای شروع رصد یک دوره‌ی واقعی، یکی از بالا بسازید.",
            style={"color": TEXT_MUTED, "fontSize": "13px"},
        )
    return [build_instance_row(inst, steps, editing_instance_id=editing_instance_id) for inst in instances]


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


def build_designer_page(roles: list[dict], versions: list[dict], selected_version: dict, instances: list[dict]):
    steps = selected_version["steps"] if selected_version else []
    return html.Div(
        [
            html.Div(id="version-bar-container", children=build_version_bar(versions, selected_version)),
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
                                    html.Button("ذخیره‌ی تغییرات", id="save-steps-btn", n_clicks=0),
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
                            html.Div(id="save-steps-status", style={"color": TEXT_SECONDARY, "fontSize": "12px", "marginTop": "10px"}),
                        ],
                    ),
                ],
            ),
            html.Div(
                style={**CARD_STYLE, "marginTop": "20px"},
                children=[
                    html.Div("نمونه‌ها — دوره‌های در حال اجرای این گردش‌کار", style={"fontWeight": "600", "marginBottom": "4px"}),
                    html.Div(
                        "هر نمونه، مرحله‌ی فعلی خودش را دنبال می‌کند. برای مشخص‌کردن مرحله‌ی فعلی هر دوره، روی یکی از مراحل زیر آن نمونه کلیک کنید.",
                        style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px"},
                    ),
                    html.Div(
                        style={"display": "flex", "gap": "10px", "alignItems": "center", "marginBottom": "16px"},
                        children=[
                            dcc.Input(
                                id="new-instance-name",
                                type="text",
                                placeholder="مثلاً «بودجه‌ی سالانه‌ی ۱۴۰۵»",
                                style={"width": "260px", "height": "34px"},
                            ),
                            html.Button("ایجاد نمونه", id="create-instance-btn", n_clicks=0),
                            html.Div(id="create-instance-status", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
                        ],
                    ),
                    html.Div(id="instance-list", children=build_instance_list(instances, steps)),
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
        "title": "نسخه‌ها",
        "body": "از این نوار بالای صفحه یک نسخه‌ی جدید بسازید، بین نسخه‌های موجود سوییچ کنید، یا یکی را به‌عنوان نسخه‌ی فعال مشخص کنید.",
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
        "title": "نمونه‌ها",
        "body": "برای هر دوره‌ی واقعی (مثلاً بودجه‌ی یک سال خاص) یک نمونه بسازید و با کلیک روی مراحل، مرحله‌ی فعلی‌اش را مشخص کنید.",
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


def build_module_content(module_id: str, roles, versions, selected_version, instances):
    if module_id in PLACEHOLDER_MODULES:
        return build_placeholder_module(module_id)
    return build_designer_page(roles, versions, selected_version, instances)


def build_shell(roles, versions, selected_version, instances, active_module: str = "workflow"):
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
                        data=[{"role_id": s["role_id"], "label": s["label"]} for s in (selected_version["steps"] if selected_version else [])],
                    ),
                    # Which role, if any, is currently showing its inline
                    # rename form in the roles panel - see
                    # build_role_palette/edit_role.
                    dcc.Store(id="editing-role-id", data=None),
                    # Same idea, for one instance's name - see
                    # build_instance_row/callbacks.edit_instance_name.
                    dcc.Store(id="editing-instance-id", data=None),
                    # Delete is destructive (drops that instance's whole
                    # progress history) and has no undo, unlike a rename -
                    # so it goes through a native confirm prompt instead of
                    # firing straight from the 🗑 click.
                    # pending-delete-instance-id remembers *which* instance
                    # the confirm is about between the "ask" and "confirmed"
                    # callbacks (see callbacks.ask_delete_instance/
                    # confirm_delete_instance).
                    dcc.ConfirmDialog(id="delete-instance-confirm", message=""),
                    dcc.Store(id="pending-delete-instance-id", data=None),
                    html.Div(id="module-header", children=build_module_header(active_module)),
                    html.Div(
                        id="page-content",
                        children=build_module_content(active_module, roles, versions, selected_version, instances),
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

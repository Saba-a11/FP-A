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


def build_role_palette(roles: list[dict]):
    """Drag-only role chips for the designer page.

    Deliberately carries no editing affordances any more: adding, renaming,
    setting an assignee and deleting all live in the settings module now
    (build_role_manager). This is a narrow left-hand column beside a canvas
    that wants every pixel of width, so anything that is not "grab a role and
    drop it on a stage" was moved out of it.
    """
    chips = []
    for role in roles:
        label_children = [html.Span(role["role_name"], className="fpa-role-chip-label")]
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


def build_role_manager(roles: list[dict], editing_role_id: int | None = None):
    """Full role administration for the settings module: add, rename, set who
    holds the role, delete.

    `editing_role_id` swaps exactly one row into an inline edit form - see
    callbacks.edit_role, the only thing that ever sets it. Same pattern the
    designer palette used to carry, moved here so the design canvas keeps its
    width for the thing it is actually for.
    """
    input_style = {
        "width": "100%",
        "background": "var(--fpa-surface)",
        "border": "1px solid var(--fpa-border)",
        "borderRadius": "6px",
        "color": "var(--fpa-text)",
        "padding": "6px 9px",
        "fontSize": "12.5px",
    }
    rows = []
    for role in roles:
        if role["role_id"] == editing_role_id:
            rows.append(
                html.Div(
                    className="fpa-role-manager-row fpa-role-manager-row-editing",
                    style={"--role-color": role["color_hex"]},
                    children=[
                        html.Div(
                            style={"display": "flex", "gap": "8px", "flexWrap": "wrap"},
                            children=[
                                dcc.Input(
                                    id={"type": "role-name-input", "role_id": role["role_id"]},
                                    value=role["role_name"],
                                    type="text",
                                    placeholder="نام نقش",
                                    autoFocus=True,
                                    style={**input_style, "flex": "1", "minWidth": "140px"},
                                ),
                                dcc.Input(
                                    id={"type": "role-assignee-name-input", "role_id": role["role_id"]},
                                    value=role.get("assignee_name") or "",
                                    type="text",
                                    placeholder="نام مسئول (اختیاری)",
                                    style={**input_style, "flex": "1", "minWidth": "140px"},
                                ),
                                dcc.Input(
                                    id={"type": "role-assignee-email-input", "role_id": role["role_id"]},
                                    value=role.get("assignee_email") or "",
                                    type="email",
                                    placeholder="ایمیل مسئول (اختیاری)",
                                    style={**input_style, "flex": "1", "minWidth": "160px", "direction": "ltr"},
                                ),
                            ],
                        ),
                        html.Div(
                            [
                                html.Button(
                                    "🗑 حذف نقش",
                                    id={"type": "role-delete-btn", "role_id": role["role_id"]},
                                    n_clicks=0,
                                    className="fpa-btn-danger",
                                    style={"fontSize": "11.5px", "padding": "5px 12px"},
                                ),
                                html.Div(style={"flex": "1"}),
                                html.Button(
                                    "ذخیره",
                                    id={"type": "role-name-save", "role_id": role["role_id"]},
                                    n_clicks=0,
                                    style={"fontSize": "11.5px", "padding": "5px 14px"},
                                ),
                                html.Button(
                                    "انصراف",
                                    id={"type": "role-name-cancel", "role_id": role["role_id"]},
                                    n_clicks=0,
                                    className="fpa-btn-quiet",
                                    style={"border": f"1px solid {BORDER}", "fontSize": "11.5px", "padding": "5px 14px"},
                                ),
                            ],
                            style={"display": "flex", "gap": "8px", "alignItems": "center", "marginTop": "10px"},
                        ),
                    ],
                )
            )
        else:
            meta = []
            if role.get("assignee_name"):
                meta.append(role["assignee_name"])
            if role.get("assignee_email"):
                meta.append(role["assignee_email"])
            rows.append(
                html.Div(
                    className="fpa-role-manager-row",
                    style={"--role-color": role["color_hex"]},
                    children=[
                        html.Span(role["role_name"][:1], className="fpa-role-badge"),
                        html.Div(
                            [
                                html.Div(role["role_name"], style={"fontWeight": "700", "fontSize": "13px"}),
                                html.Div(
                                    " — ".join(meta) if meta else "مسئولی تعیین نشده",
                                    style={
                                        "fontSize": "11px",
                                        "color": TEXT_SECONDARY if meta else TEXT_MUTED,
                                        "marginTop": "2px",
                                    },
                                ),
                            ],
                            style={"flex": "1", "minWidth": "0"},
                        ),
                        html.Button(
                            "ویرایش",
                            id={"type": "role-chip-label", "role_id": role["role_id"]},
                            n_clicks=0,
                            className="fpa-btn-quiet",
                            style={"border": f"1px solid {BORDER}", "fontSize": "11.5px", "padding": "4px 12px"},
                        ),
                    ],
                )
            )
    return rows


def build_canvas_children(stages: list[list[dict]]):
    """The columns shown inside #fpa-canvas for one version's step list.

    `stages` is workflow.get_version()["stages"] - one inner list per stage,
    where a stage holding more than one step is a set of parallel branches.
    Every chip carries data-* attributes because dragdrop.js reads them back
    off the DOM when a drag starts.

    This markup must stay byte-for-byte equivalent to dragdrop.js's own
    render()/stageHtml()/chipHtml(), which repaints this same node on every
    client-side edit - the split-ownership rule (see build_steps_payload)
    means Dash paints it once and the JS owns it from then on, so any drift
    between the two shows up as the canvas visibly changing shape on the
    first drag.
    """
    if not stages:
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

    def gap(index: int):
        return html.Div(
            className="fpa-gap",
            title="نقش را اینجا رها کنید تا یک مرحله‌ی جدید ساخته شود",
            **{"data-gap": index},
            children=[
                html.Div(className="fpa-gap-line"),
                html.Div("+", className="fpa-gap-badge"),
                html.Div("مرحله‌ی جدید", className="fpa-gap-label"),
                html.Div(className="fpa-gap-line"),
            ],
        )

    children = [gap(0)]
    for stage_index, stage in enumerate(stages):
        is_parallel = len(stage) > 1
        head_children = [html.Span(f"مرحله {stage_index + 1}", className="fpa-stage-num")]
        if is_parallel:
            head_children.append(
                html.Span(f"همزمان · {len(stage)} نفر", className="fpa-stage-tag")
            )

        body_children = []
        for step in stage:
            body_children.append(
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
                        html.Span((step["role_name"] or step["label"])[:1], className="fpa-role-badge"),
                        html.Span(step["label"]),
                        html.Button("×", className="fpa-remove", **{"data-key": f"s{step['step_id']}"}),
                    ],
                )
            )
        body_children.append(
            html.Div(
                [
                    "+ افزودن نقش به این مرحله",
                    html.Span("همزمان با بقیه", className="fpa-stage-drop-sub"),
                ],
                className="fpa-stage-drop",
            )
        )

        stage_children = [
            html.Div(head_children, className="fpa-stage-head"),
            html.Div(body_children, className="fpa-stage-body"),
        ]
        if is_parallel:
            stage_children.append(
                html.Div(f"هر {len(stage)} نفر باید تایید کنند", className="fpa-stage-note")
            )
        children.append(
            html.Div(
                stage_children,
                className="fpa-stage fpa-stage-parallel" if is_parallel else "fpa-stage",
                **{"data-stage": stage_index},
            )
        )
        children.append(gap(stage_index + 1))
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


def step_state_badge(step: dict):
    """The small status pill on one step in the progress track. Reads
    instance_progress's annotation only - it never re-decides whose turn it
    is, so the track can't disagree with the engine."""
    if step["state"] == "approved":
        text, color, bg = "✓ تایید شد", GOOD_COLOR, "var(--fpa-good-soft)"
    elif step["state"] == "rejected":
        text, color, bg = "↩ عدم تایید", CRITICAL_COLOR, "var(--fpa-critical-soft)"
    elif step["is_actionable"]:
        text, color, bg = "● در انتظار اقدام", ACCENT, "var(--fpa-hover-overlay)"
    else:
        text, color, bg = "— نوبت نرسیده", TEXT_MUTED, "transparent"
    return html.Span(
        text,
        style={
            "color": color,
            "background": bg,
            "border": f"1px solid {color}",
            "borderRadius": "999px",
            "padding": "2px 9px",
            "fontSize": "10.5px",
            "fontWeight": "700",
            "whiteSpace": "nowrap",
        },
    )


def build_track_step(instance_id: int, step: dict):
    """One step inside one stage column of the progress track.

    Approve/reject render *only* on a step that is actionable right now -
    that is the whole of the "each person acts only on their own step, and
    only when it reaches them" rule as far as the UI is concerned.
    workflow.approve_step/reject_step enforce the same thing server-side, so
    hiding a button is a convenience, never the actual guard.

    Reject is additionally withheld on the first stage, which has nobody
    behind it to send the work back to (reject_step refuses it too).
    """
    children = [
        html.Div(
            [
                html.Span(step["label"], style={"fontWeight": "700", "fontSize": "12.5px"}),
                step_state_badge(step),
            ],
            style={"display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap"},
        )
    ]
    if step.get("assignee_name"):
        children.append(
            html.Div(step["assignee_name"], style={"fontSize": "11px", "color": TEXT_SECONDARY, "marginTop": "2px"})
        )
    if step["state"] == "rejected" and step.get("state_note"):
        children.append(
            html.Div(
                f"« {step['state_note']} »",
                style={"fontSize": "11px", "color": CRITICAL_COLOR, "marginTop": "4px"},
            )
        )

    if step["is_actionable"]:
        actions = [
            html.Button(
                "تایید و ارسال",
                id={"type": "approve-step-btn", "instance_id": instance_id, "step_id": step["step_id"]},
                n_clicks=0,
                className="fpa-approve-btn",
                title="تایید این مرحله و ارسال به مرحله‌ی بعد",
            )
        ]
        if step["stage_index"] > 0:
            actions.append(
                html.Button(
                    "عدم تایید",
                    id={"type": "reject-step-btn", "instance_id": instance_id, "step_id": step["step_id"]},
                    n_clicks=0,
                    className="fpa-btn-danger fpa-reject-btn",
                    title="بازگرداندن به مرحله‌ی قبل همراه با توضیح",
                )
            )
        if step.get("is_optional"):
            actions.append(
                html.Button(
                    "رد کردن",
                    id={"type": "skip-step-btn", "instance_id": instance_id, "step_id": step["step_id"]},
                    n_clicks=0,
                    className="fpa-btn-quiet",
                    style={"border": f"1px solid {BORDER}", "fontSize": "11px", "padding": "3px 9px"},
                    title="این مرحله اختیاری است و می‌تواند رد شود",
                )
            )
        children.append(
            html.Div(actions, style={"display": "flex", "gap": "6px", "marginTop": "8px", "flexWrap": "wrap"})
        )

    css_class = "fpa-track-step"
    if step["state"] == "approved":
        css_class += " fpa-track-step-done"
    elif step["state"] == "rejected":
        css_class += " fpa-track-step-rejected"
    elif step["is_actionable"]:
        css_class += " fpa-track-step-active"
    return html.Div(children, className=css_class, style={"--role-color": step["color_hex"]})


def build_instance_row(
    instance: dict,
    progress: dict,
    editing_instance_id: int | None = None,
    history: list[dict] | None = None,
    expanded_history_instance_id: int | None = None,
):
    """One workflow's live progress: stage columns, who can act, history.

    `progress` is workflow.instance_progress's return - the single read
    model. Nothing here recomputes whose turn it is.
    """
    stages = progress["stages"]
    instance_id = instance["instance_id"]

    track_children = []
    for stage_index, stage in enumerate(stages):
        if stage_index > 0:
            connector_class = "fpa-track-connector"
            if progress["stage_complete"][stage_index - 1]:
                connector_class += " fpa-connector-done"
            track_children.append(html.Div(className=connector_class))
        # Its own class, not the canvas's .fpa-stage-head: the canvas header
        # is a bar inside a bordered card, while this is a plain caption over
        # a borderless column. Sharing one class coupled two layouts that
        # only happen to show similar text.
        column_children = [
            html.Div(
                f"مرحله {stage_index + 1}" + (" — همزمان" if len(stage) > 1 else ""),
                className="fpa-track-stage-head",
            )
        ]
        column_children.extend(build_track_step(instance_id, step) for step in stage)
        track_children.append(html.Div(column_children, className="fpa-track-stage"))

    waiting_on = [s for stage in stages for s in stage if s["is_actionable"]]
    if not stages:
        banner = html.Div(
            "این نسخه هنوز مرحله‌ای ندارد - چند مرحله در بوم بالا اضافه کنید.",
            style={"color": TEXT_MUTED, "fontSize": "12.5px", "marginBottom": "10px"},
        )
    elif progress["is_complete"]:
        banner = html.Div("🏁 این فرایند کامل شده است.", className="fpa-current-banner")
    else:
        banner = html.Div(
            "📍 اکنون در انتظار: " + "، ".join(s["label"] for s in waiting_on),
            className="fpa-current-banner",
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

    # Overdue badges, one per waiting step that has an sla_days set (opt-in
    # per step). Measured from that step's own state timestamp - how long
    # *this* person has had it - rather than the instance's updated_at,
    # which with parallel branches moves whenever any branch acts and so
    # would keep resetting everyone else's clock.
    header_extra = []
    for step in waiting_on:
        if not step.get("sla_days") or not step.get("state_updated_at"):
            continue
        elapsed_days = (datetime.now() - step["state_updated_at"]).days
        if elapsed_days > step["sla_days"]:
            header_extra.append(
                html.Span(
                    f"⚠ {step['label']}: {elapsed_days} روز (مهلت {step['sla_days']} روز)",
                    style={
                        "color": CRITICAL_COLOR,
                        "background": "var(--fpa-critical-soft)",
                        "border": f"1px solid {CRITICAL_COLOR}",
                        "borderRadius": "999px",
                        "padding": "3px 10px",
                        "fontSize": "11px",
                        "fontWeight": "700",
                    },
                )
            )
    header_extra.append(
        html.Button(
            "▶ شروع مجدد",
            id={"type": "restart-instance-btn", "instance_id": instance["instance_id"]},
            n_clicks=0,
            className="fpa-btn-quiet",
            style={"border": f"1px solid {BORDER}", "fontSize": "11px", "padding": "4px 10px"},
            title="همه‌ی مراحل به حالت اولیه برمی‌گردد و فرایند از ابتدا شروع می‌شود",
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

    action_fa = {
        "advance": "شروع",
        "approve": "تایید",
        "reject": "عدم تایید",
        "skip": "رد (اختیاری)",
    }
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
    progress: dict | None,
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
    if not instances or progress is None:
        return html.Div(
            "گردش‌کاری انتخاب نشده.",
            style={"color": TEXT_MUTED, "fontSize": "13px"},
        )
    history_by_instance = history_by_instance or {}
    return [
        build_instance_row(
            inst,
            progress,
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
                # Without these two the JS would fall back to "one step per
                # stage" on every reload and silently flatten a parallel
                # design back into a linear one - see syncFromServerIfNeeded.
                "stage": s["stage"],
                "lane": s["lane"],
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
    return [
        {
            "role_id": s["role_id"],
            "label": s["label"],
            "key": f"s{s['step_id']}",
            "stage": s["stage"],
            "lane": s["lane"],
        }
        for s in steps
    ]


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
    stages = version["stages"] if version else []
    return html.Div(
        id="fpa-canvas-dropzone",
        className="fpa-canvas-dropzone",
        # The step sequence reads as a left-to-right flow (like any
        # flowchart/timeline) even in an otherwise-RTL Persian page - see
        # the same reasoning on .fpa-track in build_instance_row.
        style={"direction": "ltr"},
        children=[
            build_steps_payload(version),
            # Zoom-to-fit, rather than a horizontal scrollbar: the viewport is
            # the visible width, the scaler holds the flow at its natural size
            # and dragdrop.js's fitCanvas() shrinks it with a CSS transform
            # until it fits. That keeps every stage on one left-to-right line
            # and on screen at once however many there are, which is what a
            # scrollbar (you can only ever see part of the process) and
            # wrapping (the flow breaks mid-line) both fail to do.
            #
            # Scaling is safe for drag-and-drop here because dropTargetFrom()
            # resolves the target with event.target.closest(), i.e. from the
            # DOM, never from raw clientX coordinates that a transform would
            # have to be undone from.
            html.Div(
                id="fpa-canvas-viewport",
                className="fpa-canvas-viewport",
                children=html.Div(
                    id="fpa-canvas-scaler",
                    className="fpa-canvas-scaler",
                    children=[
                        # START/END are pure decoration - never touched by Dash
                        # again after this first render, and never touched by
                        # dragdrop.js either (it only ever repaints #fpa-canvas),
                        # so they can't conflict with either side's ownership.
                        html.Div("شروع", className="fpa-endpoint"),
                        html.Span("→", className="fpa-arrow"),
                        html.Div(id="fpa-canvas", className="fpa-canvas", children=build_canvas_children(stages)),
                        html.Span("→", className="fpa-arrow"),
                        html.Div("پایان", className="fpa-endpoint"),
                    ],
                ),
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


def reject_backdrop_style(hidden: bool) -> dict:
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


def build_reject_modal():
    """The comment box a rejection has to go through.

    Rejecting is never a bare button click: the person sending work back
    always states why first, and that text is what
    fpna.notify.format_step_message puts in the Telegram message the
    previous person receives (its دلیل بازگشت line). workflow.reject_step
    refuses an empty note independently, so this is the prompt, not the
    validation.

    Rendered once as part of the first page load and never removed, like
    build_step_detail_modal - see that function's docstring for why an id
    born later inside a callback-injected subtree fails Dash's client-side
    callback validation.
    """
    return html.Div(
        id="reject-backdrop",
        style=reject_backdrop_style(hidden=True),
        children=html.Div(
            style={
                **CARD_STYLE,
                "width": "min(440px, 92vw)",
                "position": "relative",
                "boxShadow": "0 20px 48px var(--fpa-shadow-lg)",
            },
            children=[
                html.Div("عدم تایید و بازگشت به مرحله‌ی قبل", style={"fontWeight": "700", "fontSize": "15px", "marginBottom": "4px"}),
                html.Div(
                    id="reject-modal-subtitle",
                    style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "12px"},
                ),
                html.Label("دلیل عدم تایید (الزامی)", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
                dcc.Textarea(
                    id="reject-note-input",
                    placeholder="مثلاً: ارقام بخش فروش با صورت مالی مغایرت دارد و باید اصلاح شود.",
                    style={"width": "100%", "minHeight": "90px", "marginTop": "6px"},
                ),
                html.Div(
                    id="reject-modal-status",
                    style={"color": CRITICAL_COLOR, "fontSize": "11.5px", "marginTop": "6px", "minHeight": "16px"},
                ),
                html.Div(
                    [
                        html.Button(
                            "انصراف",
                            id="reject-cancel-btn",
                            n_clicks=0,
                            className="fpa-btn-quiet",
                            style={"border": f"1px solid {BORDER}"},
                        ),
                        html.Div(style={"flex": "1"}),
                        html.Button(
                            "ثبت عدم تایید و ارسال",
                            id="reject-confirm-btn",
                            n_clicks=0,
                            className="fpa-btn-danger",
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center", "gap": "8px", "marginTop": "14px"},
                ),
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


def build_schedule_rows(schedules: list[dict]):
    """The table of scheduled kick-offs in the settings module."""
    if not schedules:
        return html.Div(
            "هنوز زمان‌بندی‌ای تعریف نشده.",
            style={"color": TEXT_MUTED, "fontSize": "12.5px"},
        )
    rows = []
    for schedule in schedules:
        fired = schedule["last_run_at"] is not None and (
            schedule["run_at"] is None or schedule["last_run_at"] >= schedule["run_at"]
        )
        if not schedule["enabled"]:
            status_text, status_color = "غیرفعال", TEXT_MUTED
        elif fired:
            status_text, status_color = "✓ اجرا شد", GOOD_COLOR
        else:
            status_text, status_color = "● در انتظار", ACCENT
        rows.append(
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "12px",
                    "flexWrap": "wrap",
                    "padding": "10px 12px",
                    "border": f"1px solid {BORDER}",
                    "borderRadius": "8px",
                    "background": "var(--fpa-surface-2)",
                },
                children=[
                    html.Div(
                        [
                            html.Div(schedule["version_name"], style={"fontWeight": "700", "fontSize": "13px"}),
                            html.Div(
                                schedule["run_at"].strftime("%Y-%m-%d %H:%M") if schedule["run_at"] else "",
                                style={"fontSize": "11.5px", "color": TEXT_SECONDARY, "marginTop": "2px", "direction": "ltr"},
                            ),
                        ],
                        style={"flex": "1", "minWidth": "160px"},
                    ),
                    html.Span(
                        status_text,
                        style={
                            "color": status_color,
                            "border": f"1px solid {status_color}",
                            "borderRadius": "999px",
                            "padding": "2px 10px",
                            "fontSize": "11px",
                            "fontWeight": "700",
                        },
                    ),
                    html.Button(
                        "غیرفعال کردن" if schedule["enabled"] else "فعال کردن",
                        id={"type": "schedule-toggle-btn", "schedule_id": schedule["schedule_id"]},
                        n_clicks=0,
                        className="fpa-btn-quiet",
                        style={"border": f"1px solid {BORDER}", "fontSize": "11px", "padding": "4px 10px"},
                    ),
                    html.Button(
                        "🗑",
                        id={"type": "schedule-delete-btn", "schedule_id": schedule["schedule_id"]},
                        n_clicks=0,
                        className="fpa-btn-danger",
                        style={"fontSize": "12px", "padding": "3px 10px"},
                        title="حذف این زمان‌بندی",
                    ),
                ],
            )
        )
    return html.Div(rows, style={"display": "flex", "flexDirection": "column", "gap": "8px"})


def build_roles_settings_card(roles: list[dict], editing_role_id: int | None = None):
    return html.Div(
        style={**CARD_STYLE, "marginBottom": "20px"},
        children=[
            html.Div("نقش‌ها", style={"fontWeight": "600", "marginBottom": "2px"}),
            html.Div(
                "نقش‌هایی که در طراحی گردش‌کار استفاده می‌شوند. برای هر نقش می‌توانید نام مسئول و ایمیل او را هم ثبت کنید.",
                style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px"},
            ),
            html.Div(
                style={"display": "flex", "gap": "10px", "alignItems": "center", "flexWrap": "wrap", "marginBottom": "16px"},
                children=[
                    dcc.Input(
                        id="new-role-name",
                        type="text",
                        placeholder="نام نقش جدید",
                        style={"width": "240px", "height": "34px"},
                    ),
                    html.Button("+ افزودن نقش", id="add-role-btn", n_clicks=0),
                    html.Div(id="add-role-status", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
                ],
            ),
            html.Div(
                id="role-manager",
                children=build_role_manager(roles, editing_role_id),
                style={"display": "flex", "flexDirection": "column", "gap": "8px"},
            ),
        ],
    )


def build_settings_page(versions: list[dict], schedules: list[dict], roles: list[dict] | None = None):
    """Settings: role administration and scheduled kick-offs.

    Roles live here rather than on the designer page because managing them
    is occasional configuration, while the designer page needs its width for
    the canvas - the palette there is now drag-sources only.

    A schedule says "put this workflow into motion at this moment" - firing
    it resets every step to pending and notifies the first stage, exactly
    as the manual "شروع مجدد" button does (both go through
    workflow.start_workflow).

    Timing is checked by the dashboard's own 5-second tick, so a schedule
    fires while the dashboard is open and otherwise fires the first time it
    is opened after the due moment - never silently skipped, never fired
    twice (workflow.due_schedules/mark_schedule_run). That trade is stated
    on the page itself rather than left for someone to discover.
    """
    return html.Div(
        [
            build_roles_settings_card(roles or []),
            html.Div(
                style={**CARD_STYLE, "marginBottom": "20px"},
                children=[
                    html.Div("زمان‌بندی شروع خودکار گردش‌کار", style={"fontWeight": "600", "marginBottom": "2px"}),
                    html.Div(
                        "یک گردش‌کار از پیش تعریف‌شده را انتخاب کنید تا در تاریخ و ساعت مشخصی به‌طور خودکار به جریان بیفتد.",
                        style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px"},
                    ),
                    html.Div(
                        style={"display": "flex", "gap": "12px", "alignItems": "flex-end", "flexWrap": "wrap"},
                        children=[
                            html.Div(
                                [
                                    html.Label("گردش‌کار", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
                                    dcc.Dropdown(
                                        id="schedule-version-picker",
                                        options=version_options(versions),
                                        value=versions[0]["version_id"] if versions else None,
                                        clearable=False,
                                        style={"width": "280px"},
                                    ),
                                ]
                            ),
                            html.Div(
                                [
                                    html.Label("تاریخ", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
                                    dcc.DatePickerSingle(
                                        id="schedule-date-picker",
                                        display_format="YYYY-MM-DD",
                                        placeholder="انتخاب تاریخ",
                                    ),
                                ]
                            ),
                            html.Div(
                                [
                                    html.Label("ساعت (۲۴ ساعته)", style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
                                    dcc.Input(
                                        id="schedule-time-input",
                                        type="text",
                                        value="09:00",
                                        placeholder="09:00",
                                        style={"width": "110px", "height": "34px", "direction": "ltr", "textAlign": "center"},
                                    ),
                                ]
                            ),
                            html.Button("افزودن زمان‌بندی", id="schedule-add-btn", n_clicks=0),
                        ],
                    ),
                    html.Div(id="schedule-add-status", style={"color": TEXT_SECONDARY, "fontSize": "12px", "marginTop": "10px"}),
                    html.Div(
                        "توجه: بررسی زمان‌بندی‌ها توسط همین داشبورد انجام می‌شود. اگر در لحظه‌ی سررسید داشبورد باز نباشد، "
                        "زمان‌بندی حذف نمی‌شود و در اولین باری که داشبورد باز شود اجرا خواهد شد.",
                        style={"color": TEXT_MUTED, "fontSize": "11.5px", "marginTop": "12px", "lineHeight": "1.7"},
                    ),
                ],
            ),
            html.Div(
                style={**CARD_STYLE},
                children=[
                    html.Div("زمان‌بندی‌های تعریف‌شده", style={"fontWeight": "600", "marginBottom": "12px"}),
                    html.Div(id="schedule-list", children=build_schedule_rows(schedules)),
                ],
            ),
        ]
    )


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
    progress: dict | None = None,
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
                    # Canvas FIRST in DOM order, roles second. The page is
                    # RTL, so the first flex child sits on the right (next to
                    # the sidebar) - putting the canvas first is what lands
                    # the roles column on the LEFT edge, mirroring the
                    # reference design where the palette sits opposite the
                    # menu. No flexWrap: the roles column must never drop
                    # below the canvas and steal a whole row.
                    html.Div(
                        style={"display": "flex", "gap": "16px", "alignItems": "flex-start"},
                        children=[
                            html.Div(
                                # flex-basis 0 so the canvas card never forces
                                # a line break and simply takes every pixel
                                # the roles column does not - same reasoning
                                # as .fpa-canvas itself in style.css.
                                style={**CARD_STYLE, "flex": "1 1 0", "minWidth": "0"},
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
                                        [
                                            html.Div(
                                                "هر کادر یک «مرحله» است. نقشی که داخل یک کادر بیفتد، همزمان با بقیه‌ی نقش‌های همان کادر کار می‌کند و مرحله‌ی بعد تا تایید همه‌ی آن‌ها شروع نمی‌شود.",
                                                style={"marginBottom": "6px"},
                                            ),
                                            html.Div(
                                                [
                                                    html.Span("◀ ", style={"color": ACCENT}),
                                                    "برای ",
                                                    html.B("مرحله‌ی جدید"),
                                                    "، نقش را روی نوار نقطه‌چین ",
                                                    html.B("بین"),
                                                    " دو کادر رها کنید.",
                                                ]
                                            ),
                                            html.Div(
                                                [
                                                    html.Span("◀ ", style={"color": ACCENT}),
                                                    "برای ",
                                                    html.B("همزمان‌کردن"),
                                                    " با یک مرحله‌ی موجود، نقش را ",
                                                    html.B("داخل"),
                                                    " همان کادر رها کنید.",
                                                ]
                                            ),
                                            html.Div(
                                                "برای جابه‌جایی، خودِ مرحله را بکشید؛ برای حذف، آن را به سطل زباله بکشید.",
                                                style={"marginTop": "6px"},
                                            ),
                                        ],
                                        style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px", "lineHeight": "1.9"},
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
                            # The roles column - second child, so RTL puts it
                            # on the far left, opposite the sidebar. Drag
                            # sources only; everything about *managing* roles
                            # now lives in the settings module, linked below.
                            html.Div(
                                style={**CARD_STYLE, "width": "190px", "flexShrink": "0", "padding": "16px 14px"},
                                children=[
                                    html.Div("نقش‌ها", style={"fontWeight": "600", "marginBottom": "4px"}),
                                    html.Div(
                                        "یک نقش را بکشید و روی یک مرحله رها کنید.",
                                        style={"color": TEXT_MUTED, "fontSize": "11.5px", "marginBottom": "12px", "lineHeight": "1.7"},
                                    ),
                                    html.Div(build_role_palette(roles), id="role-palette", className="fpa-role-palette"),
                                    html.Div(
                                        style={"borderTop": f"1px solid {BORDER}", "marginTop": "14px", "paddingTop": "12px"},
                                        children=[
                                            html.Button(
                                                "⚙  مدیریت نقش‌ها",
                                                # A pattern-matching id, not a
                                                # plain string one, because this
                                                # button only exists on the
                                                # designer page while the
                                                # callback it feeds
                                                # (switch_module) stays live on
                                                # every module. A plain string
                                                # Input that disappears while
                                                # its callback is still
                                                # resolvable is exactly what
                                                # Dash reports as "a
                                                # nonexistent object was used
                                                # in an Input"; an ALL matcher
                                                # is allowed to match nothing.
                                                id={"type": "goto-module-btn", "module": "settings"},
                                                n_clicks=0,
                                                className="fpa-btn-quiet",
                                                style={
                                                    "border": f"1px solid {BORDER}",
                                                    "width": "100%",
                                                    "fontSize": "11.5px",
                                                    "padding": "7px 8px",
                                                },
                                                title="افزودن، ویرایش و حذف نقش‌ها در بخش تنظیمات",
                                            ),
                                        ],
                                    ),
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
                                "هر نفر فقط روی مرحله‌ی خودش و فقط وقتی نوبتش رسیده باشد می‌تواند اقدام کند: "
                                "«تایید و ارسال» کار را به مرحله‌ی بعد می‌فرستد و «عدم تایید» آن را همراه با توضیح به مرحله‌ی قبل بازمی‌گرداند.",
                                style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "14px", "lineHeight": "1.8"},
                            ),
                            html.Div(
                                id="instance-list",
                                children=build_instance_list(
                                    instances,
                                    progress,
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
        "body": "هر ستون یک مرحله است. نقش را روی فاصله‌ی بین ستون‌ها رها کنید تا مرحله‌ی جدیدی ساخته شود، یا روی خودِ یک ستون رها کنید تا آن نقش همزمان با بقیه‌ی افراد آن ستون کار کند. پس از هر تغییر، «ذخیره‌ی تغییرات» را بزنید.",
    },
    {
        "title": "مراحل همزمان",
        "body": "اگر چند نقش در یک ستون باشند، کار همزمان برای همه‌شان ارسال می‌شود و مرحله‌ی بعدی تا وقتی همه‌ی آن‌ها تایید نکنند شروع نمی‌شود.",
    },
    {
        "title": "تایید و عدم تایید",
        "body": "در تب «نمونه‌های در حال اجرا»، هر نفر فقط روی مرحله‌ی خودش و فقط وقتی نوبتش رسیده باشد دکمه دارد: «تایید و ارسال» به مرحله‌ی بعد می‌فرستد، و «عدم تایید» با نوشتن دلیل، کار را به مرحله‌ی قبل بازمی‌گرداند.",
    },
    {
        "title": "زمان‌بندی",
        "body": "در بخش «تنظیمات» می‌توانید مشخص کنید یک گردش‌کار در چه تاریخ و ساعتی به‌طور خودکار به جریان بیفتد.",
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
    {"id": "settings", "icon": "⚙️", "label": "تنظیمات"},
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
    progress: dict | None = None,
    schedules: list[dict] | None = None,
):
    if module_id in PLACEHOLDER_MODULES:
        return build_placeholder_module(module_id)
    if module_id == "settings":
        return build_settings_page(versions, schedules or [], roles)
    return build_designer_page(
        roles,
        versions,
        selected_version,
        instances,
        status_summary,
        history_by_instance,
        expanded_history_instance_id,
        progress=progress,
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
    progress: dict | None = None,
    schedules: list[dict] | None = None,
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
                    # Which step a rejection is being written for, held
                    # between the "عدم تایید" click that opens the comment
                    # box and the confirm that actually submits it - see
                    # build_reject_modal/callbacks.open_reject_modal.
                    dcc.Store(id="pending-reject-step-id", data=None),
                    build_reject_modal(),
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
                            progress=progress,
                            schedules=schedules,
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

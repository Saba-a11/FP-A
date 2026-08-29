"""Telegram notifications for the budgeting workflow.

One shared channel (config.TELEGRAM_CHAT_ID) stands in for real email for
now, per the project's grill-me session: this app already tracks who is
(nominally) behind a role via dim_role.assignee_name, but there's no mail
server wired up yet - see send_email/SendEmail.py for what that would
eventually look like (a corporate SMTP login, out of scope until it's
actually available). Every notification instead names the responsible
person/role in the message text of a single shared channel, rather than
DMing them individually (which would need each person's own Telegram
chat_id, captured by having them message the bot first - deliberately
deferred, see Q5 of that session).

Sending never blocks or raises past this module's own boundary - a failed
Telegram call must never stop a step transition from being saved (see
callbacks.py's set_current_step call sites) - so every public function here
returns (ok, error) instead of raising, and logs the failure itself.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from . import config

logger = logging.getLogger(__name__)

_TELEGRAM_API_MESSAGE = "https://api.telegram.org/bot{token}/sendMessage"
_TELEGRAM_API_DOCUMENT = "https://api.telegram.org/bot{token}/sendDocument"
_TIMEOUT_SECONDS = 10
# Telegram caption limit - a step's full detail (duty/input/output/
# acceptance) can easily run past this, which is exactly why the file is
# sent as its own message with a short caption rather than as one
# sendDocument call carrying format_step_message's full text as caption
# (that would silently truncate instead of failing loudly).
_CAPTION_MAX_CHARS = 1024

# Plain text on purpose, no parse_mode: step text (duty/input_desc/etc.) is
# free-form user input that can contain "*", "_", "[" and similar - asking
# Telegram to parse that as Markdown risks a "can't parse entities" 400 on
# otherwise-harmless text. A closer look than this app needs, given
# notifications are best-effort already.
def send_message(text: str) -> tuple[bool, str | None]:
    """POSTs `text` to config.TELEGRAM_CHAT_ID. Never raises - a missing
    token/chat id or any network/API failure comes back as (False, reason)
    for the caller to log/surface as a non-blocking warning instead.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False, "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID در .env تنظیم نشده است"

    url = _TELEGRAM_API_MESSAGE.format(token=config.TELEGRAM_BOT_TOKEN)
    try:
        response = requests.post(
            url,
            data={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
            timeout=_TIMEOUT_SECONDS,
        )
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("Telegram notification failed: %s", exc)
        return False, str(exc)
    except ValueError:
        logger.warning("Telegram notification failed: non-JSON response (status %s)", response.status_code)
        return False, f"پاسخ نامعتبر از تلگرام (status {response.status_code})"

    if not payload.get("ok"):
        error = payload.get("description", "خطای نامشخص")
        logger.warning("Telegram notification failed: %s", error)
        return False, error
    return True, None


def send_document(file_path: Path, caption: str | None = None, filename: str | None = None) -> tuple[bool, str | None]:
    """POSTs the file at `file_path` to config.TELEGRAM_CHAT_ID as a
    document attachment. Same (ok, error) contract and same
    never-raises-past-this-module rule as send_message - a missing/unreadable
    file or any network/API failure comes back as (False, reason) instead of
    raising, so a step transition still saves even if the file never made it
    to Telegram (see the module docstring).

    `caption` is sent as Telegram's own short caption for the document (max
    _CAPTION_MAX_CHARS) - callers should NOT pass the full
    format_step_message text here (see that constant's comment); pair this
    with a separate send_message call for the full detail instead.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False, "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID در .env تنظیم نشده است"
    if not file_path.exists():
        logger.warning("Telegram document send failed: file not found: %s", file_path)
        return False, f"فایل یافت نشد: {file_path.name}"

    url = _TELEGRAM_API_DOCUMENT.format(token=config.TELEGRAM_BOT_TOKEN)
    data = {"chat_id": config.TELEGRAM_CHAT_ID}
    if caption:
        data["caption"] = caption[:_CAPTION_MAX_CHARS]
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                url,
                data=data,
                files={"document": (filename or file_path.name, f)},
                timeout=_TIMEOUT_SECONDS,
            )
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("Telegram document send failed: %s", exc)
        return False, str(exc)
    except ValueError:
        logger.warning("Telegram document send failed: non-JSON response (status %s)", response.status_code)
        return False, f"پاسخ نامعتبر از تلگرام (status {response.status_code})"

    if not payload.get("ok"):
        error = payload.get("description", "خطای نامشخص")
        logger.warning("Telegram document send failed: %s", error)
        return False, error
    return True, None


# 'skip' (workflow.skip_current_step, an optional step bypassed with no
# human action) is worded the same as 'advance': either way, the instance
# just landed on a new current step and whoever is responsible for it needs
# to know work has arrived on their desk.
_EVENT_LABEL_FA = {
    "advance": "ارسال شد به",
    "skip": "ارسال شد به",
    "reject": "بازگردانده شد به",
}


def _default_subject(instance: dict, step: dict, event: str) -> str:
    if event == "reject":
        return f"بازگشت مرحله - {instance['version_name']} - {step['label']}"
    return f"اعلان مرحله جدید - {instance['version_name']} - {step['label']}"


_DIVIDER = "──────────"


def format_step_message(instance: dict, step: dict, event: str, note: str | None = None, is_final_step: bool = False) -> str:
    """Builds the standard Persian message body for one step transition -
    the one fixed shape every notification uses, so whoever reads the
    channel always finds the same field in the same place regardless of
    which step or process it's about.

    `step` is a dict shaped like workflow.get_step's return (label,
    role_name, assignee_name, duty, input_desc, output_desc,
    acceptance_criteria, sla_days, notification_subject, template_path,
    template_original_name) - the step the instance is *now* sitting on,
    whichever way it got there. Every per-step detail field is optional in
    the DB (see the step-detail editor), so each line below only appears
    when that field is actually filled in - a step with nothing set still
    gets a valid, non-empty message (the header block alone).

    `is_final_step` covers the "پایان فرایند" case agreed in the grill-me
    session: this data model has no distinct "instance complete" state (the
    last step just stays current once nobody advances it further - see
    workflow.set_current_step), so reaching it is signaled by appending a
    closing note to that step's own notification rather than sending a
    second, detail-free message.

    The template file itself (if any) is never inlined here - Telegram
    captions/messages can't carry binary content - only *mentioned*.
    notify_step_change decides how it actually reaches the reader: normally
    as this same text used as the file's own caption (one message, not two -
    see that function), so whoever needs the file gets it and its context
    together instead of having to match up two separate messages.
    """
    subject = step.get("notification_subject") or _default_subject(instance, step, event)
    responsible = step.get("assignee_name") or step["role_name"]
    lines = [
        "📋 اعلان گردش‌کار بودجه‌ریزی",
        _DIVIDER,
        f"عنوان: {subject}",
        f"فرایند: {instance['version_name']} — نمونه: {instance['name']}",
        f"مرحله: {step['label']}",
        f"وضعیت: {_EVENT_LABEL_FA.get(event, event)} {responsible}",
        _DIVIDER,
    ]

    if step.get("duty"):
        lines.append(f"🗂 وظیفه: {step['duty']}")
    if step.get("input_desc"):
        lines.append(f"📥 ورودی: {step['input_desc']}")
    if step.get("output_desc"):
        lines.append(f"📤 خروجی: {step['output_desc']}")
    if step.get("acceptance_criteria"):
        lines.append(f"✅ شرایط پذیرش خروجی: {step['acceptance_criteria']}")
    if step.get("sla_days"):
        lines.append(f"⏳ مهلت: {step['sla_days']} روز")
    if step.get("template_path"):
        lines.append(f"📎 فایل الگو پیوست است: {step.get('template_original_name') or 'پیوست شده'}")
    if event == "reject" and note:
        lines.append(f"↩️ دلیل بازگشت: {note}")
    if is_final_step:
        lines.append("🏁 این آخرین مرحله‌ی فرایند است.")

    return "\n".join(lines)


def notify_step_change(
    instance: dict, step: dict, event: str, note: str | None = None, is_final_step: bool = False
) -> tuple[bool, str | None]:
    """The one entry point callbacks.py calls after every
    workflow.set_current_step/skip_current_step (and, for a workflow's very
    first real step, save_steps) - builds the standard message and sends it
    to whoever is now responsible for this step.

    Uploading a template file to a step (workflow.save_step_template) never
    sends anything by itself - the file only ever goes out bundled with the
    one notification that's actually addressed to the role who needs it,
    i.e. right here, when that step becomes current. When it does, the file
    is the carrier: it's sent as a single sendDocument call with the full
    standard message as its own caption, so the person gets the file and
    its context in one message instead of two easy-to-separate ones. Only
    if that text doesn't fit in a Telegram caption (_CAPTION_MAX_CHARS) does
    this fall back to two messages - full text first, then the file with a
    short reference caption - so real detail is never silently truncated.

    Returns (ok, error) for the primary send (the caption+file message, or
    the text message when there's no file) - a failed *secondary* send in
    the fallback path is independently logged (see send_document) and never
    overrides that primary result, since the responsible person still got
    the actionable text either way.
    """
    text = format_step_message(instance, step, event, note, is_final_step)
    template_path = step.get("template_path")
    if not template_path:
        return send_message(text)

    abs_path = config.PROJECT_ROOT / template_path
    original_name = step.get("template_original_name") or abs_path.name
    if len(text) <= _CAPTION_MAX_CHARS:
        return send_document(abs_path, caption=text, filename=original_name)

    ok, error = send_message(text)
    send_document(
        abs_path,
        caption=f"📎 فایل الگو — {instance['version_name']} / {step['label']}",
        filename=original_name,
    )
    return ok, error

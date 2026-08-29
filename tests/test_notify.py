from fpna import config, notify


def _instance(**overrides):
    base = {"version_name": "Budgeting_Workflow", "name": "FY2027 Annual Budget"}
    base.update(overrides)
    return base


def _step(**overrides):
    base = {
        "label": "Finance Review",
        "role_name": "Finance Reviewer",
        "assignee_name": None,
        "duty": None,
        "input_desc": None,
        "output_desc": None,
        "acceptance_criteria": None,
        "sla_days": None,
        "notification_subject": None,
        "template_path": None,
        "template_original_name": None,
    }
    base.update(overrides)
    return base


def test_format_step_message_includes_all_filled_fields():
    text = notify.format_step_message(
        _instance(),
        _step(
            assignee_name="Alex",
            duty="Review the numbers",
            input_desc="Draft budget",
            output_desc="Approved budget",
            acceptance_criteria="Matches board guidance",
            sla_days=3,
            template_path="data/templates/step_1/plan.xlsx",
            template_original_name="plan.xlsx",
        ),
        "advance",
    )
    assert "Finance Review" in text
    assert "Alex" in text
    assert "🗂 وظیفه: Review the numbers" in text
    assert "📥 ورودی: Draft budget" in text
    assert "📤 خروجی: Approved budget" in text
    assert "✅ شرایط پذیرش خروجی: Matches board guidance" in text
    assert "⏳ مهلت: 3 روز" in text
    assert "📎 فایل الگو پیوست است: plan.xlsx" in text


def test_format_step_message_omits_empty_fields():
    text = notify.format_step_message(_instance(), _step(), "advance")
    for marker in ["🗂", "📥", "📤", "✅", "⏳", "📎"]:
        assert marker not in text


def test_format_step_message_reject_includes_note():
    text = notify.format_step_message(_instance(), _step(), "reject", note="Numbers don't add up")
    assert "↩️ دلیل بازگشت: Numbers don't add up" in text


def test_format_step_message_final_step_banner():
    text = notify.format_step_message(_instance(), _step(), "advance", is_final_step=True)
    assert "🏁 این آخرین مرحله‌ی فرایند است." in text


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_notify_step_change_bundles_file_and_full_text_in_one_message(monkeypatch, tmp_path):
    # When the standard message fits in a Telegram caption (the normal
    # case), the file should carry it - one message, not two - so the
    # person who needs the file gets it together with its context.
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "test-chat")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    template_dir = tmp_path / "data" / "templates" / "step_1"
    template_dir.mkdir(parents=True)
    (template_dir / "plan.xlsx").write_bytes(b"fake spreadsheet bytes")

    calls = []

    def fake_post(url, data=None, files=None, timeout=None):
        calls.append({"url": url, "data": data, "files": files})
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(notify.requests, "post", fake_post)

    step = _step(
        template_path="data/templates/step_1/plan.xlsx",
        template_original_name="plan.xlsx",
        duty="Review the numbers",
    )
    expected_text = notify.format_step_message(_instance(), step, "advance")
    ok, error = notify.notify_step_change(_instance(), step, "advance")

    assert ok is True
    assert error is None
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/sendDocument")
    assert calls[0]["files"]["document"][0] == "plan.xlsx"
    assert calls[0]["data"]["caption"] == expected_text


def test_notify_step_change_falls_back_to_two_messages_when_text_too_long(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "test-chat")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    template_dir = tmp_path / "data" / "templates" / "step_1"
    template_dir.mkdir(parents=True)
    (template_dir / "plan.xlsx").write_bytes(b"fake spreadsheet bytes")

    calls = []

    def fake_post(url, data=None, files=None, timeout=None):
        calls.append({"url": url, "data": data, "files": files})
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(notify.requests, "post", fake_post)

    step = _step(
        template_path="data/templates/step_1/plan.xlsx",
        template_original_name="plan.xlsx",
        duty="x" * 2000,  # long enough to blow past the 1024-char caption limit
    )
    ok, error = notify.notify_step_change(_instance(), step, "advance")

    assert ok is True
    assert error is None
    assert len(calls) == 2
    assert calls[0]["url"].endswith("/sendMessage")
    assert "x" * 2000 in calls[0]["data"]["text"]
    assert calls[1]["url"].endswith("/sendDocument")
    assert len(calls[1]["data"]["caption"]) <= 1024


def test_notify_step_change_skips_document_when_no_template(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "test-chat")

    calls = []

    def fake_post(url, data=None, files=None, timeout=None):
        calls.append(url)
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(notify.requests, "post", fake_post)

    notify.notify_step_change(_instance(), _step(), "advance")

    assert len(calls) == 1
    assert calls[0].endswith("/sendMessage")


def test_send_document_reports_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "test-chat")

    ok, error = notify.send_document(tmp_path / "does_not_exist.xlsx")

    assert ok is False
    assert "یافت نشد" in error


def test_send_message_reports_missing_credentials(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", None)

    ok, error = notify.send_message("hello")

    assert ok is False
    assert error

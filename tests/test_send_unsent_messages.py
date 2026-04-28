from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

import surveys.management.commands.send_unsent_messages as command_module


def test_send_unsent_messages_dry_run_prints_counts(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "count_outbox_rows",
        lambda: {"PENDING": 7, "FAILED": 2},
    )

    def _fail_start(_loop):
        raise AssertionError("dry run should not start messaging")

    monkeypatch.setattr(command_module, "start_outbox_messaging", _fail_start)

    stdout = StringIO()
    call_command("send_unsent_messages", dry_run=True, stdout=stdout)

    assert "pending=7 failed=2" in stdout.getvalue()


def test_send_unsent_messages_publishes_until_empty(monkeypatch):
    calls = []

    class FakeRelay:
        process_count = 0

        def process_batch(self, batch_size):
            self.process_count += 1
            calls.append(batch_size)
            return 2 if self.process_count == 1 else 0

    async def _stop():
        calls.append("stop")

    monkeypatch.setattr(
        command_module,
        "start_outbox_messaging",
        lambda _loop: calls.append("start"),
    )
    monkeypatch.setattr(command_module, "get_messaging", lambda: object())
    monkeypatch.setattr(
        command_module,
        "build_outbox_relay",
        lambda _messaging, *, subject_prefix: FakeRelay(),
    )
    monkeypatch.setattr(command_module, "stop_messaging", _stop)

    stdout = StringIO()
    call_command("send_unsent_messages", batch_size=5, stdout=stdout)

    assert calls == ["start", 5, 5, "stop"]
    assert "Published outbox rows: 2" in stdout.getvalue()


def test_send_unsent_messages_honors_limit(monkeypatch):
    calls = []

    class FakeRelay:
        def process_batch(self, batch_size):
            calls.append(batch_size)
            return batch_size

    async def _stop():
        calls.append("stop")

    monkeypatch.setattr(
        command_module,
        "start_outbox_messaging",
        lambda _loop: calls.append("start"),
    )
    monkeypatch.setattr(command_module, "get_messaging", lambda: object())
    monkeypatch.setattr(
        command_module,
        "build_outbox_relay",
        lambda _messaging, *, subject_prefix: FakeRelay(),
    )
    monkeypatch.setattr(command_module, "stop_messaging", _stop)

    stdout = StringIO()
    call_command("send_unsent_messages", batch_size=2, limit=5, stdout=stdout)

    assert calls == ["start", 2, 2, 1, "stop"]
    assert "Published outbox rows: 5" in stdout.getvalue()


def test_send_unsent_messages_can_reset_failed_rows(monkeypatch):
    calls = []

    class FakeRelay:
        def process_batch(self, batch_size):
            calls.append(batch_size)
            return 0

    async def _stop():
        calls.append("stop")

    monkeypatch.setattr(
        command_module,
        "reset_failed_outbox_rows",
        lambda: calls.append("reset") or 3,
    )
    monkeypatch.setattr(
        command_module,
        "start_outbox_messaging",
        lambda _loop: calls.append("start"),
    )
    monkeypatch.setattr(command_module, "get_messaging", lambda: object())
    monkeypatch.setattr(
        command_module,
        "build_outbox_relay",
        lambda _messaging, *, subject_prefix: FakeRelay(),
    )
    monkeypatch.setattr(command_module, "stop_messaging", _stop)

    stdout = StringIO()
    call_command("send_unsent_messages", include_failed=True, stdout=stdout)

    assert calls == ["reset", "start", 50, "stop"]
    assert "Reset failed outbox rows: 3" in stdout.getvalue()


@pytest.mark.parametrize("option,value", [("batch_size", 0), ("limit", 0)])
def test_send_unsent_messages_rejects_non_positive_options(option, value):
    with pytest.raises(CommandError):
        call_command("send_unsent_messages", **{option: value})

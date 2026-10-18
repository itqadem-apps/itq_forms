"""`manage.py relay` (forms:AD-26), on SQLite with a fake cursor.

`DjangoOutboxRelay` speaks Postgres-only SQL, so the cursor it uses is faked;
what is under test is the claim/publish/mark sequence, the transaction around
it, the heartbeat rule and the command's loop.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import signal
from types import SimpleNamespace

import pytest
from django.core.management import get_commands
from django.core.management.base import CommandError
from django.test import override_settings
from unimessaging.outbox_django import relay as pkg_relay
from unimessaging.outbox_django.relay import DjangoOutboxRelay

from app import messaging_contract as contract
from surveys.management.commands import relay as relay_cmd


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self._result = []
        self.description = None
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "FOR UPDATE SKIP LOCKED" in sql:
            self._result = [(r["id"],) for r in self._rows]
        elif sql.startswith("SELECT * FROM"):
            columns = list(self._rows[0]) if self._rows else []
            self.description = [(c,) for c in columns]
            self._result = [tuple(r[c] for c in columns) for r in self._rows]
        else:
            self._result = []

    def fetchall(self):
        return self._result


class FakeClient:
    def __init__(self):
        self.published = []

    async def publish(self, subject, data, headers=None):
        self.published.append((subject, data, headers))


@pytest.fixture
def event_loop_set():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    asyncio.set_event_loop(None)
    loop.close()


def _row(row_id, payload):
    return {
        "id": row_id,
        "aggregate_type": "survey",
        "payload": payload,
        "status": "PENDING",
        "retries": 0,
    }


@pytest.mark.parametrize(
    "payload",
    [
        '{"survey_id": "s1", "n": 1}',  # psycopg returns jsonb as text
        {"survey_id": "s1", "n": 1},  # an adapter that decodes it
    ],
)
def test_pending_row_published_once_encoded_with_msg_id_and_marked(
    monkeypatch, event_loop_set, payload
):
    cursor = FakeCursor([_row(7, payload)])
    monkeypatch.setattr(pkg_relay, "connection", SimpleNamespace(cursor=lambda: cursor))
    client = FakeClient()
    relay = DjangoOutboxRelay(relay_cmd.PayloadPassthrough(client), subject_prefix="forms")

    assert relay.process_batch(50) == 1

    [(subject, data, headers)] = client.published
    assert subject == "forms.survey"
    assert headers == {"Nats-Msg-Id": "7"}
    assert json.loads(data) == {"survey_id": "s1", "n": 1}
    mark = [(sql, p) for sql, p in cursor.executed if "status='PUBLISHED'" in sql]
    assert mark and mark[0][1] == [7]


def test_run_pass_runs_batch_inside_atomic_after_close_old_connections(
    monkeypatch, tmp_path
):
    calls = []

    @contextlib.contextmanager
    def atomic():
        calls.append("atomic-enter")
        yield
        calls.append("atomic-exit")

    monkeypatch.setattr(relay_cmd, "close_old_connections", lambda: calls.append("close"))
    monkeypatch.setattr(relay_cmd, "transaction", SimpleNamespace(atomic=atomic))

    class Relay:
        def process_batch(self, batch_size):
            calls.append(("batch", batch_size))
            return 3

    hb = tmp_path / "hb"
    assert relay_cmd.run_pass(Relay(), 25, str(hb)) == 3
    assert calls == ["close", "atomic-enter", ("batch", 25), "atomic-exit"]
    assert hb.exists()


def test_empty_pass_touches_heartbeat(tmp_path):
    class Relay:
        def process_batch(self, batch_size):
            return 0

    hb = tmp_path / "hb"
    assert relay_cmd.run_pass(Relay(), 50, str(hb)) == 0
    assert hb.exists()


def test_raising_pass_rolls_back_and_leaves_heartbeat_untouched(monkeypatch, tmp_path):
    exits = []

    @contextlib.contextmanager
    def atomic():
        try:
            yield
        except BaseException as exc:
            exits.append(type(exc))
            raise

    monkeypatch.setattr(relay_cmd, "transaction", SimpleNamespace(atomic=atomic))

    class Relay:
        def process_batch(self, batch_size):
            raise RuntimeError("db down")

    hb = tmp_path / "hb"
    with pytest.raises(RuntimeError):
        relay_cmd.run_pass(Relay(), 50, str(hb))
    assert exits == [RuntimeError]
    assert not hb.exists()


class FakeBroker:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.client = FakeClient()
        self.started = False
        self.stopped = False
        FakeBroker.instances.append(self)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


@override_settings(
    SERVICE_NAME="forms",
    NATS_URL="nats://example:4222",
    JETSTREAM_ENABLED=True,
    OUTBOX_BATCH_SIZE=17,
    OUTBOX_POLL_INTERVAL=0.001,
    OUTBOX_SUBJECT_PREFIX="forms",
)
def test_handle_builds_publish_only_forms_broker_and_stops_on_flag(monkeypatch, tmp_path):
    FakeBroker.instances = []
    monkeypatch.setattr(relay_cmd, "UnifiedMessageBroker", FakeBroker)
    cursor = FakeCursor([_row(7, '{"survey_id": "s1", "n": 1}')])
    monkeypatch.setattr(pkg_relay, "connection", SimpleNamespace(cursor=lambda: cursor))
    hb_path = str(tmp_path / "hb")
    prior = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    cmd = relay_cmd.Command()
    seen = []

    def fake_run_pass(relay, batch_size, heartbeat_path):
        loop = asyncio.get_event_loop()
        seen.append((relay, batch_size, heartbeat_path, loop, loop.is_running()))
        assert FakeBroker.instances[0].started
        assert signal.getsignal(signal.SIGTERM) == cmd.request_stop
        assert signal.getsignal(signal.SIGINT) == cmd.request_stop
        if len(seen) == 1:
            raise RuntimeError("transient")  # the loop survives a failed pass
        published = relay.process_batch(batch_size)
        cmd.request_stop()
        return published

    monkeypatch.setattr(relay_cmd, "run_pass", fake_run_pass)
    with override_settings(OUTBOX_RELAY_HEARTBEAT_PATH=hb_path):
        cmd.handle()

    assert {sig: signal.getsignal(sig) for sig in prior} == prior

    [broker] = FakeBroker.instances
    kw = broker.kwargs
    assert kw["service_name"] == "forms"
    assert kw["url"] == "nats://example:4222"
    assert kw["enable_durable"] is True
    assert kw["stream_name"] == contract.FORMS_STREAM_NAME
    assert kw["stream_subjects"] == contract.FORMS_STREAM_SUBJECTS
    assert kw["consumers"] == []
    assert kw["subjects"] == []
    assert kw["registry"] is not None
    assert not kw["registry"]._handlers
    assert broker.stopped

    [(subject, data, headers)] = broker.client.published
    assert subject == "forms.survey"
    assert headers == {"Nats-Msg-Id": "7"}
    assert json.loads(data) == {"survey_id": "s1", "n": 1}

    assert len(seen) == 2
    relay, batch_size, heartbeat_path, loop, running = seen[0]
    assert isinstance(relay, DjangoOutboxRelay)
    assert batch_size == 17
    assert heartbeat_path == hb_path
    assert running is False
    assert seen[1][3] is loop
    assert loop.is_closed()


@override_settings(JETSTREAM_ENABLED=False)
def test_handle_refuses_without_jetstream(monkeypatch):
    FakeBroker.instances = []
    monkeypatch.setattr(relay_cmd, "UnifiedMessageBroker", FakeBroker)
    prior = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    with pytest.raises(CommandError):
        relay_cmd.Command().handle()
    assert FakeBroker.instances == []
    assert {sig: signal.getsignal(sig) for sig in prior} == prior


def test_relay_command_is_discoverable_in_surveys():
    assert get_commands()["relay"] == "surveys"


@override_settings(MESSAGING_STOP_TIMEOUT=0.05, OUTBOX_POLL_INTERVAL=0.001)
def test_handle_bounds_a_hanging_broker_stop(monkeypatch, tmp_path):
    class HangingBroker(FakeBroker):
        async def stop(self):
            while True:
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    continue

    FakeBroker.instances = []
    monkeypatch.setattr(relay_cmd, "UnifiedMessageBroker", HangingBroker)
    cmd = relay_cmd.Command()
    monkeypatch.setattr(relay_cmd, "run_pass", lambda *a: cmd.request_stop() or 0)
    with override_settings(OUTBOX_RELAY_HEARTBEAT_PATH=str(tmp_path / "hb")):
        cmd.handle()  # returns instead of hanging


def test_settings_heartbeat_defaults_match_the_probe():
    from django.conf import settings

    from app import heartbeat

    assert settings.OUTBOX_RELAY_HEARTBEAT_PATH == heartbeat.path_for("relay")
    assert settings.OUTBOX_RELAY_HEARTBEAT_MAX_AGE == heartbeat.DEFAULT_MAX_AGE == 180.0


def test_stale_heartbeat_is_removed_at_start(tmp_path, monkeypatch):
    hb = tmp_path / "hb"
    hb.touch()
    seen = []
    cmd = relay_cmd.Command()

    def first_pass(*_a):
        seen.append(hb.exists())
        cmd.request_stop()
        return 0

    FakeBroker.instances = []
    monkeypatch.setattr(relay_cmd, "UnifiedMessageBroker", FakeBroker)
    monkeypatch.setattr(relay_cmd, "run_pass", first_pass)
    with override_settings(OUTBOX_RELAY_HEARTBEAT_PATH=str(hb)):
        cmd.handle()
    assert seen == [False]


def test_module_never_uses_the_stock_standalone_relay():
    source = inspect.getsource(relay_cmd)
    assert "run_standalone_relay" not in source
    assert "outbox_relay" not in source

"""``manage.py consume`` binds every durable in one process (forms:AD-26)."""
import asyncio
import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from django.core.management import CommandError, call_command, get_commands
from django.test import override_settings

from app.messaging import runtime
from surveys.management.commands import consume
from tests.test_durable_limits import EXPECTED_DURABLES


class _FakeBroker:
    instances: list = []
    fail_on_start: set = set()
    hang_on_stop: set = set()

    def __init__(self, *, consumers=None, **kwargs):
        self.consumers = list(consumers or [])
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.label = len(_FakeBroker.instances)
        _FakeBroker.instances.append(self)

    async def start(self):
        if self.label in _FakeBroker.fail_on_start:
            raise RuntimeError("limits refused")
        self.started = True

    async def stop(self):
        if self.label in _FakeBroker.hang_on_stop:
            await asyncio.Event().wait()
        self.stopped = True


@pytest.fixture
def fake_brokers(monkeypatch, tmp_path, settings):
    _FakeBroker.instances = []
    _FakeBroker.fail_on_start = set()
    _FakeBroker.hang_on_stop = set()
    monkeypatch.setattr(runtime, "UnifiedMessageBroker", _FakeBroker)
    monkeypatch.setattr(runtime, "_consumer_brokers", [])
    settings.MESSAGING_STOP_TIMEOUT = 0.05
    settings.JETSTREAM_ENABLED = True
    settings.CONSUMERS_HEARTBEAT_PATH = str(tmp_path / "consumers.heartbeat")
    return _FakeBroker


DURABLES_BY_LABEL = {
    "forms": {
        "forms-auth-user-registered-consumer",
        "forms-external-reference-events-consumer",
        "forms-external-reference-events-consumer-enrollment",
        "forms-recommendables-courses-consumer",
        "forms-recommendables-videos-consumer",
        "forms-recommendables-articles-consumer",
        "forms-recommendables-reservations-consumer",
    },
    "users": {"forms-users-child-consumer", "forms-users-child_guardian-consumer"},
    "orders": {"forms-orders-order-consumer"},
    "taxonomy": {"forms-taxonomy-category-consumer"},
}


def _by_label(brokers):
    # Keyed by the label bound into each broker's on_tick, not by build order.
    return {b.kwargs["on_tick"].args[0]: b for b in brokers}


def _heartbeat(tmp_path):
    return runtime.AllBrokersTicked(tmp_path / "hb", runtime.CONSUMER_BROKER_LABELS)


def test_all_ticked_touches_once_and_clears(tmp_path):
    hb = _heartbeat(tmp_path)
    for label in ("forms", "users", "orders"):
        hb.tick(label)
    assert not hb.path.exists()
    hb.tick("taxonomy")
    assert hb.path.exists()
    hb.path.unlink()
    hb.tick("forms")
    assert not hb.path.exists(), "tick set must be cleared after a touch"


def test_one_stalled_broker_never_touches(tmp_path):
    hb = _heartbeat(tmp_path)
    for _ in range(20):
        for label in ("forms", "users", "orders"):
            hb.tick(label)
    assert not hb.path.exists()


def test_repeat_ticks_from_one_broker_do_not_touch(tmp_path):
    hb = _heartbeat(tmp_path)
    for _ in range(50):
        hb.tick("orders")
    assert not hb.path.exists()


def test_start_consumers_binds_exactly_the_known_durables(fake_brokers, tmp_path):
    asyncio.run(runtime.start_consumers(_heartbeat(tmp_path)))
    brokers = fake_brokers.instances
    assert len(brokers) == 4
    durables = [c.durable for b in brokers for c in b.consumers]
    assert len(durables) == len(set(durables)), durables
    assert set(durables) == EXPECTED_DURABLES
    for b in brokers:
        for c in b.consumers:
            assert c.limits is not None, c.durable
            assert c.limits.max_deliver == 5, c.durable
            assert c.limits.ack_wait == 60.0, c.durable
            assert c.limits.nak_delays == (1.0, 5.0, 30.0, 120.0), c.durable
        assert b.kwargs.get("stream_name") is None
        assert b.kwargs.get("stream_subjects") is None
        assert callable(b.kwargs["on_tick"])


def test_each_broker_gets_its_own_consumer_set(fake_brokers, tmp_path):
    asyncio.run(runtime.start_consumers(_heartbeat(tmp_path)))
    by_label = _by_label(fake_brokers.instances)
    assert set(by_label) == set(DURABLES_BY_LABEL)
    for label, broker in by_label.items():
        assert {c.durable for c in broker.consumers} == DURABLES_BY_LABEL[label], label


@override_settings(
    SERVICE_NAME="forms-test",
    NATS_URL="nats://nats.test:4222",
    JETSTREAM_ENABLED=True,
    JETSTREAM_PULL_BATCH=7,
    JETSTREAM_PULL_TIMEOUT=2.5,
)
def test_brokers_take_connection_and_pull_settings(fake_brokers, tmp_path):
    asyncio.run(runtime.start_consumers(_heartbeat(tmp_path)))
    for b in fake_brokers.instances:
        assert b.kwargs["enable_durable"] is True
        assert b.kwargs["service_name"] == "forms-test"
        assert b.kwargs["url"] == "nats://nats.test:4222"
        assert b.kwargs["pull_batch"] == 7
        assert b.kwargs["pull_timeout"] == 2.5


def test_each_broker_on_tick_feeds_the_heartbeat(fake_brokers, tmp_path):
    hb = _heartbeat(tmp_path)
    asyncio.run(runtime.start_consumers(hb))
    ticks = [b.kwargs["on_tick"] for b in fake_brokers.instances]
    for on_tick in ticks[:-1]:
        on_tick()
    assert not hb.path.exists()
    ticks[-1]()
    assert hb.path.exists()


def test_stop_is_bounded_when_a_broker_hangs(fake_brokers, tmp_path, caplog):
    fake_brokers.hang_on_stop = {1}

    async def run():
        await runtime.start_consumers(_heartbeat(tmp_path))
        await asyncio.wait_for(runtime.stop_consumers(), timeout=2)

    asyncio.run(run())
    brokers = fake_brokers.instances
    assert [b.stopped for b in brokers] == [True, False, True, True]
    assert "Timed out" in caplog.text
    assert runtime._consumer_brokers == []


def test_start_failure_stops_started_brokers_and_reraises(fake_brokers, tmp_path):
    fake_brokers.fail_on_start = {2}
    with pytest.raises(RuntimeError, match="limits refused"):
        asyncio.run(runtime.start_consumers(_heartbeat(tmp_path)))
    brokers = fake_brokers.instances
    assert [b.stopped for b in brokers] == [True, True, False]
    assert runtime._consumer_brokers == []


def test_command_stops_on_sigterm(fake_brokers, monkeypatch, settings):
    calls = []
    monkeypatch.setattr(
        consume,
        "register_handlers",
        lambda: calls.append(len(fake_brokers.instances)),
    )

    async def stop_soon(stop):
        asyncio.get_running_loop().call_later(0.05, os.kill, os.getpid(), consume.signal.SIGTERM)
        await original(stop)

    original = consume.run_consumers
    monkeypatch.setattr(consume, "run_consumers", stop_soon)
    call_command("consume")
    assert calls == [0], "register_handlers must run once, before any broker is built"
    assert len(fake_brokers.instances) == 4
    assert all(b.stopped for b in fake_brokers.instances)

    heartbeat = consume.Path(settings.CONSUMERS_HEARTBEAT_PATH)
    assert not heartbeat.exists()
    for b in fake_brokers.instances:
        b.kwargs["on_tick"]()
    assert heartbeat.exists()


def test_command_removes_a_stale_heartbeat_before_starting(fake_brokers, monkeypatch, settings):
    monkeypatch.setattr(consume, "register_handlers", lambda: None)
    heartbeat = consume.Path(settings.CONSUMERS_HEARTBEAT_PATH)
    heartbeat.touch()
    seen = []

    async def start_consumers(hb):
        seen.append(heartbeat.exists())
        raise RuntimeError("stop here")

    monkeypatch.setattr(runtime, "start_consumers", start_consumers)
    with pytest.raises(RuntimeError, match="stop here"):
        call_command("consume")
    assert seen == [False]


def test_command_refuses_without_jetstream(fake_brokers, monkeypatch, settings):
    calls = []
    monkeypatch.setattr(consume, "register_handlers", lambda: calls.append(1))
    settings.JETSTREAM_ENABLED = False
    with pytest.raises(CommandError, match="JETSTREAM_ENABLED"):
        call_command("consume")
    assert calls == []
    assert fake_brokers.instances == []


def test_command_start_failure_propagates(fake_brokers, monkeypatch):
    monkeypatch.setattr(consume, "register_handlers", lambda: None)
    fake_brokers.fail_on_start = {0}
    with pytest.raises(RuntimeError, match="limits refused"):
        call_command("consume")


def test_command_lives_beside_relay():
    commands = get_commands()
    assert commands["consume"] == "surveys"
    assert commands["consume"] == commands["relay"]

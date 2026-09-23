"""Shutdown finishes on a deadline even when a broker never stops.

A blocked `broker.stop()` used to hang the ASGI lifespan handler in
`app/asgi.py`. Uvicorn waits for `lifespan.shutdown.complete` with no deadline
of its own, so the worker never exited and the pod survived until Kubernetes
force-killed it — long enough for `kubectl rollout status` to report the
deploy failed while the new version was already serving (deploy-forms-r825n,
v0.0.64, "1 old replicas are pending termination").
"""
import asyncio
import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from django.test import override_settings

from app.messaging import runtime


class _HangingBroker:
    """Never returns from stop(), and ignores cancellation on the way out."""

    def __init__(self):
        self.stop_called = False

    async def stop(self):
        self.stop_called = True
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                # Deliberately swallowed: this is what makes `asyncio.wait_for`
                # insufficient, since it awaits the cancellation it requests.
                continue


class _CleanBroker:
    def __init__(self):
        self.stop_called = False

    async def stop(self):
        self.stop_called = True


@pytest.fixture(autouse=True)
def _fast_timeout():
    with override_settings(MESSAGING_STOP_TIMEOUT=0.05):
        yield


@pytest.fixture(autouse=True)
def _reset_runtime():
    previous = (
        runtime._users_broker,
        runtime._orders_broker,
        runtime._taxonomy_broker,
        runtime._relay_task,
    )
    yield
    (
        runtime._users_broker,
        runtime._orders_broker,
        runtime._taxonomy_broker,
        runtime._relay_task,
    ) = previous


@pytest.mark.asyncio
async def test_a_hanging_broker_does_not_hang_shutdown(monkeypatch):
    hanging = _HangingBroker()
    monkeypatch.setattr(runtime, "_taxonomy_broker", hanging)
    monkeypatch.setattr(runtime, "_orders_broker", None)
    monkeypatch.setattr(runtime, "_users_broker", None)
    monkeypatch.setattr(runtime, "_relay_task", None)
    monkeypatch.setattr(runtime, "stop_messaging", _CleanBroker().stop)

    await asyncio.wait_for(runtime.stop_all(), timeout=5)

    assert hanging.stop_called


@pytest.mark.asyncio
async def test_a_hanging_broker_does_not_strand_the_ones_after_it(monkeypatch):
    """The whole point of per-step budgets: one bad broker must not stop the
    forms broker and the others from being asked to close."""
    hanging = _HangingBroker()
    later = _CleanBroker()
    forms = _CleanBroker()
    monkeypatch.setattr(runtime, "_taxonomy_broker", hanging)
    monkeypatch.setattr(runtime, "_orders_broker", None)
    monkeypatch.setattr(runtime, "_users_broker", later)
    monkeypatch.setattr(runtime, "_relay_task", None)
    monkeypatch.setattr(runtime, "stop_messaging", forms.stop)

    await asyncio.wait_for(runtime.stop_all(), timeout=5)

    assert later.stop_called
    assert forms.stop_called


@pytest.mark.asyncio
async def test_a_broker_that_raises_is_logged_and_stepped_over(monkeypatch):
    async def boom():
        raise RuntimeError("connection already closed")

    later = _CleanBroker()

    class _Raising:
        async def stop(self):
            await boom()

    monkeypatch.setattr(runtime, "_taxonomy_broker", _Raising())
    monkeypatch.setattr(runtime, "_orders_broker", None)
    monkeypatch.setattr(runtime, "_users_broker", None)
    monkeypatch.setattr(runtime, "_relay_task", None)
    monkeypatch.setattr(runtime, "stop_messaging", later.stop)

    await asyncio.wait_for(runtime.stop_all(), timeout=5)

    assert later.stop_called


@pytest.mark.asyncio
async def test_the_cancelled_relay_task_does_not_escape_as_cancellederror(monkeypatch):
    """`Task.exception()` re-raises for a cancelled task, and CancelledError is
    a BaseException that the lifespan handler's `except Exception` would not
    catch."""
    async def _relay():
        await asyncio.sleep(3600)

    task = asyncio.ensure_future(_relay())
    await asyncio.sleep(0)
    forms = _CleanBroker()
    monkeypatch.setattr(runtime, "_relay_task", task)
    monkeypatch.setattr(runtime, "_taxonomy_broker", None)
    monkeypatch.setattr(runtime, "_orders_broker", None)
    monkeypatch.setattr(runtime, "_users_broker", None)
    monkeypatch.setattr(runtime, "stop_messaging", forms.stop)

    await asyncio.wait_for(runtime.stop_all(), timeout=5)

    assert task.cancelled()
    assert forms.stop_called

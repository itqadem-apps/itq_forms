"""`stop_consumers()` finishes on a deadline even when a broker never stops.

A blocked `broker.stop()` used to hang the web lifespan shutdown, and the pod
survived until Kubernetes force-killed it — long enough for `kubectl rollout
status` to report the deploy failed while the new version was already serving
(deploy-forms-r825n, v0.0.64, "1 old replicas are pending termination").
`manage.py consume` now stops its brokers through the same bounded steps.
"""
import asyncio
import logging
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
def _reset_runtime(monkeypatch):
    monkeypatch.setattr(runtime, "_consumer_brokers", [])


def _set_brokers(monkeypatch, *brokers):
    # stop_consumers() stops in reverse start order, so list them as started.
    monkeypatch.setattr(
        runtime,
        "_consumer_brokers",
        [(label, b) for label, b in zip(runtime.CONSUMER_BROKER_LABELS, brokers)],
    )


@pytest.mark.asyncio
async def test_a_hanging_broker_does_not_hang_shutdown(monkeypatch):
    hanging = _HangingBroker()
    _set_brokers(monkeypatch, hanging)

    await asyncio.wait_for(runtime.stop_consumers(), timeout=5)

    assert hanging.stop_called
    assert runtime._consumer_brokers == []


@pytest.mark.asyncio
async def test_a_hanging_broker_does_not_strand_the_ones_after_it(monkeypatch):
    """The whole point of per-step budgets: one bad broker must not stop the
    others from being asked to close."""
    forms = _CleanBroker()
    later = _CleanBroker()
    hanging = _HangingBroker()
    _set_brokers(monkeypatch, forms, later, _CleanBroker(), hanging)

    await asyncio.wait_for(runtime.stop_consumers(), timeout=5)

    assert hanging.stop_called
    assert later.stop_called
    assert forms.stop_called


@pytest.mark.asyncio
async def test_a_broker_that_raises_is_logged_and_stepped_over(monkeypatch, caplog):
    class _Raising:
        async def stop(self):
            raise RuntimeError("connection already closed")

    later = _CleanBroker()
    _set_brokers(monkeypatch, later, _Raising())

    with caplog.at_level(logging.ERROR, logger="app.messaging.runtime"):
        await asyncio.wait_for(runtime.stop_consumers(), timeout=5)

    assert later.stop_called
    assert any("Error stopping users consumer broker" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_cancelled_stop_does_not_escape_as_cancellederror(monkeypatch):
    """`Task.exception()` re-raises for a cancelled task, and CancelledError is
    a BaseException that a caller's `except Exception` would not catch."""
    class _Cancelled:
        async def stop(self):
            raise asyncio.CancelledError

    forms = _CleanBroker()
    _set_brokers(monkeypatch, forms, _Cancelled())

    await asyncio.wait_for(runtime.stop_consumers(), timeout=5)

    assert forms.stop_called

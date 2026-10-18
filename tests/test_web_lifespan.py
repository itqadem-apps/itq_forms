"""Web serves HTTP with no messaging runtime (forms:AD-26).

The lifespan acknowledges startup and shutdown and starts nothing: no broker,
no relay, no NATS connection. Readiness never looks at NATS, and publishing
from a request still only writes an outbox row for `manage.py relay`.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import RequestFactory, override_settings

import surveys.subjects  # noqa: F401  (registers the survey events)
from app import health
from app.messaging import runtime
from app.messaging.publisher import publish
from surveys.events import SurveyCreated
from unimessaging.outbox_django.models import OutboxRecord

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"


def _raise_on_nats_connect(*_args, **_kwargs):
    raise AssertionError("web must not connect to NATS")


# Runs in a fresh interpreter: this test module (and the rest of the suite)
# has already imported app.messaging.runtime, so an in-process check could not
# tell whether the web entry point imports it.
_LIFESPAN_PROBE = """
import asyncio, json, sys
from unittest.mock import patch
import tests_env  # noqa: F401  (the same env defaults pytest applies)

def _refuse(*_a, **_k):
    raise AssertionError("web must not start messaging")

async def drive(application):
    inbox, sent = asyncio.Queue(), []
    async def receive():
        return await inbox.get()
    async def send(message):
        sent.append(message["type"])
    await inbox.put({"type": "lifespan.startup"})
    await inbox.put({"type": "lifespan.shutdown"})
    await asyncio.wait_for(application({"type": "lifespan"}, receive, send), timeout=5)
    return sent

with patch("nats.connect", _refuse), patch(
    "unimessaging.broker.broker.UnifiedMessageBroker", _refuse
):
    from app import asgi
    sent = asyncio.run(drive(asgi.application))
    runtime_loaded = "app.messaging.runtime" in sys.modules
    from app.messaging import get_messaging
    print(json.dumps({
        "sent": sent,
        "runtime_loaded": runtime_loaded,
        "messaging_is_none": get_messaging() is None,
    }))
"""


def test_lifespan_completes_without_starting_messaging():
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["DJANGO_SETTINGS_MODULE"] = "app.settings"
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if p
    )
    proc = subprocess.run(
        [sys.executable, "-c", _LIFESPAN_PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])

    assert result["sent"] == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    assert result["runtime_loaded"] is False
    assert result["messaging_is_none"] is True


class _NoPendingMigrations:
    # The test database is built with --no-migrations, so the real plan always
    # lists every migration; the DB itself is up.
    def __init__(self, *_args, **_kwargs):
        self.loader = SimpleNamespace(graph=SimpleNamespace(leaf_nodes=list))

    def migration_plan(self, _targets):
        return []


@pytest.mark.django_db
@override_settings(NATS_URL="nats://127.0.0.1:1", REDIS_URL=None)
def test_readyz_passes_with_nats_unreachable():
    connects = []
    with (
        patch.object(health, "MigrationExecutor", _NoPendingMigrations),
        patch("nats.connect", side_effect=lambda *a, **k: connects.append(a)),
    ):
        response = health.readyz(RequestFactory().get("/readyz/"))

    assert response.status_code == 200
    assert connects == []
    assert b"nats" not in response.content.lower()


@pytest.mark.django_db
def test_publish_writes_one_pending_outbox_row():
    publish(
        SurveyCreated(
            aggregate_id=42,
            organization_id="org-1",
            survey={"id": "42", "organization_id": "org-1"},
        )
    )

    rows = list(OutboxRecord.objects.all())
    assert len(rows) == 1
    assert rows[0].status == "PENDING"
    assert rows[0].aggregate_type == "survey.created"


def test_in_process_relay_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"{runtime.__package__}.relay")


def test_web_command_defaults_to_two_workers_and_web_role():
    dockerfile = DOCKERFILE.read_text()
    assert 'ENTRYPOINT ["/app/start.sh"]' in dockerfile
    assert 'CMD ["web"]' in dockerfile
    start = (REPO_ROOT / "start.sh").read_text()
    assert '--workers "${WEB_CONCURRENCY:-2}" --timeout 120 app.asgi:application' in start

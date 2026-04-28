from __future__ import annotations

import argparse
import asyncio
import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from app import messaging_contract as contract
from accounts.management.commands.consume_auth_events import Command as AuthCommand
from accounts.management.commands import consume_auth_events as auth_module
from accounts.management.commands.consume_user_child_events import Command as ChildCommand
from accounts.management.commands import consume_user_child_events as child_module
from recommendations.management.commands.consume_recommendables import (
    Command as RecommendablesCommand,
)
from recommendations.management.commands import consume_recommendables as recommendables_module
from surveys.management.commands import consume_order_events as orders_module
from surveys.management.commands import outbox_relay as outbox_module


@pytest.fixture
def db():
    return None


def test_consume_auth_events_uses_forms_contract(monkeypatch):
    captured = {}

    async def _fake_start_messaging(**kwargs):
        captured.update(kwargs)

    async def _fake_stop_messaging():
        return None

    monkeypatch.setattr(auth_module, "start_messaging", _fake_start_messaging)
    monkeypatch.setattr(auth_module, "stop_messaging", _fake_stop_messaging)

    asyncio.run(AuthCommand()._run({"stop": True}))

    assert captured["stream_name"] == contract.FORMS_STREAM_NAME
    assert captured["stream_subjects"] == contract.FORMS_STREAM_SUBJECTS
    assert captured["consumers"] == contract.AUTH_CONSUMERS
    assert (
        captured["registry"].resolve_handler("auth.UserRegistered")
        == auth_module.handle_auth_user_registered
    )


def test_consume_user_child_events_uses_users_contract(monkeypatch):
    captured = {}

    async def _fake_start_messaging(**kwargs):
        captured.update(kwargs)

    async def _fake_stop_messaging():
        return None

    monkeypatch.setattr(child_module, "start_messaging", _fake_start_messaging)
    monkeypatch.setattr(child_module, "stop_messaging", _fake_stop_messaging)

    subjects = list(contract.USERS_CHILD_SUBJECTS)
    asyncio.run(ChildCommand()._run(subjects, {"stop": True}))

    assert captured["stream_name"] == contract.USERS_CHILD_STREAM_NAME
    assert captured["stream_subjects"] == contract.USERS_CHILD_STREAM_SUBJECTS
    assert captured["consumers"] == contract.build_users_child_consumers(subjects)
    assert captured["registry"].resolve_handler("users.child.created") == child_module.handle_child_event
    assert (
        captured["registry"].resolve_handler("users.child_guardian.created")
        == child_module.handle_child_guardian_event
    )


def test_consume_recommendables_uses_default_contract(monkeypatch):
    captured = {}

    async def _fake_start_messaging(**kwargs):
        captured.update(kwargs)

    async def _fake_stop_messaging():
        return None

    monkeypatch.setattr(recommendables_module, "start_messaging", _fake_start_messaging)
    monkeypatch.setattr(recommendables_module, "stop_messaging", _fake_stop_messaging)

    subjects = list(contract.RECOMMENDABLE_SUBJECTS)
    asyncio.run(RecommendablesCommand()._run(subjects, {"stop": True}))

    assert captured["stream_name"] == contract.FORMS_STREAM_NAME
    assert captured["stream_subjects"] == contract.FORMS_STREAM_SUBJECTS
    assert captured["consumers"] == contract.RECOMMENDABLE_CONSUMERS
    assert (
        captured["registry"].resolve_handler("courses.anything")
        == recommendables_module.handle_recommendable_event
    )


def test_consume_recommendables_override_subjects_builds_ephemeral_consumers():
    consumers = recommendables_module._build_jetstream_consumers(["taxonomy.>", "forms.>"])

    assert [(consumer.subject, consumer.durable) for consumer in consumers] == [
        ("taxonomy.>", "forms-recommendables-taxonomy-consumer"),
        ("forms.>", "forms-recommendables-forms-consumer"),
    ]


def test_outbox_relay_uses_forms_and_auth_contract(monkeypatch):
    captured = {}

    async def _fake_start_messaging(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(outbox_module, "start_messaging", _fake_start_messaging)

    loop = asyncio.new_event_loop()
    try:
        outbox_module.start_outbox_messaging(loop)
    finally:
        loop.close()

    assert captured["stream_name"] == contract.FORMS_STREAM_NAME
    assert captured["stream_subjects"] == contract.FORMS_STREAM_SUBJECTS
    assert captured["consumers"] == contract.AUTH_CONSUMERS
    assert (
        captured["registry"].resolve_handler("auth.UserRegistered")
        == outbox_module._consumer_handlers()["auth.UserRegistered"]
    )


def test_order_consumer_uses_orders_contract():
    config = orders_module._messaging_config()

    assert config.stream_name == contract.ORDERS_STREAM_NAME
    assert config.stream_subjects == contract.ORDERS_STREAM_SUBJECTS


def test_command_defaults_come_from_contract():
    parser = argparse.ArgumentParser()
    RecommendablesCommand().add_arguments(parser)
    defaults = parser.parse_args([])
    assert defaults.subjects == ",".join(contract.RECOMMENDABLE_SUBJECTS)

    parser = argparse.ArgumentParser()
    ChildCommand().add_arguments(parser)
    defaults = parser.parse_args([])
    assert defaults.subjects == ",".join(contract.USERS_CHILD_SUBJECTS)

    parser = argparse.ArgumentParser()
    orders_module.Command().add_arguments(parser)
    defaults = parser.parse_args([])
    assert defaults.subjects == ",".join(contract.ORDERS_EVENT_SUBJECTS)

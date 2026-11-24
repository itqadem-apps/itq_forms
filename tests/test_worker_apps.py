"""The relay and consume roles (forms:AD-26) load no GraphQL stack; web still does."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PROBE = (
    "import sys, django\n"
    "django.setup()\n"
    "from django.core.management import get_commands, load_command_class\n"
    "cmd = sys.argv[1]\n"
    "if cmd != 'web':\n"
    "    load_command_class(get_commands()[cmd], cmd)\n"
    "print(sorted({m.split('.')[0] for m in sys.modules} & {'strawberry', 'graphql'}))\n"
)


def _loaded(command):
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "app.settings", "PYTHONPATH": str(REPO_ROOT)}
    env.pop("DATABASE_URL", None)
    env.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-real-key")
    result = subprocess.run(
        [sys.executable, "-c", PROBE, command],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize("command", ["relay", "consume"])
def test_a_worker_loads_no_graphql_stack(command):
    assert _loaded(command) == "[]"


def test_any_other_command_keeps_strawberry_django():
    assert _loaded("web") == "['graphql', 'strawberry']"

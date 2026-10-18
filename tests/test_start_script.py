"""The image entrypoint and the worker roles' liveness check (forms:AD-26)."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import heartbeat

REPO_ROOT = Path(__file__).resolve().parent.parent
START = REPO_ROOT / "start.sh"


def _check(role, env_extra):
    # The probe runs `python`; point it at this interpreter.
    bindir = Path(sys.executable).parent
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", **env_extra}
    return subprocess.run(
        ["bash", str(START), "check", role], env=env, capture_output=True, text=True
    )


@pytest.mark.parametrize("role,var", [
    ("relay", "OUTBOX_RELAY_HEARTBEAT_PATH"),
    ("consume", "CONSUMERS_HEARTBEAT_PATH"),
])
def test_check_passes_on_a_fresh_heartbeat(tmp_path, role, var):
    hb = tmp_path / "hb"
    hb.touch()
    assert _check(role, {var: str(hb)}).returncode == 0


def test_check_fails_on_a_missing_heartbeat(tmp_path):
    result = _check("relay", {"OUTBOX_RELAY_HEARTBEAT_PATH": str(tmp_path / "none")})
    assert result.returncode == 1
    assert "missing or older" in result.stderr


def test_check_fails_on_a_stale_heartbeat(tmp_path):
    hb = tmp_path / "hb"
    hb.touch()
    old = time.time() - 181
    os.utime(hb, (old, old))
    env = {"CONSUMERS_HEARTBEAT_PATH": str(hb)}
    assert _check("consume", env).returncode == 1
    assert _check("consume", {**env, "CONSUMERS_HEARTBEAT_MAX_AGE": "600"}).returncode == 0


def test_check_rejects_an_unknown_role():
    assert _check("web", {}).returncode == 2


def test_unknown_start_role_exits_without_starting_anything():
    result = subprocess.run(["bash", str(START), "nope"], capture_output=True, text=True)
    assert result.returncode == 2


def test_heartbeat_module_imports_only_the_standard_library():
    # The probe runs it with `python -S -I`; Django or unimessaging would not
    # be importable there and would cost the probe its 5s budget.
    source = (REPO_ROOT / "app" / "heartbeat.py").read_text()
    imports = {
        line.split()[1].split(".")[0]
        for line in source.splitlines()
        if line.startswith(("import ", "from "))
    }
    assert imports <= {"__future__", "os", "sys", "time"}


def test_every_role_execs_so_it_is_pid_1():
    start = START.read_text()
    for line in (
        "exec python manage.py relay",
        "exec python manage.py consume",
        "exec gunicorn ",
    ):
        assert line in start
    assert os.access(START, os.X_OK)


def test_is_fresh_honours_max_age(tmp_path):
    hb = tmp_path / "hb"
    hb.touch()
    now = hb.stat().st_mtime
    assert heartbeat.is_fresh(str(hb), 180, now=now + 180)
    assert not heartbeat.is_fresh(str(hb), 180, now=now + 181)

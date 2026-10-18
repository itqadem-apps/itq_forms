"""Heartbeat files of the relay and consumers roles (forms:AD-26).

Standard library only. ``start.sh check relay|consume`` runs this file with
``python -S -I`` on every liveness probe, so it must not import Django or
unimessaging: ``unimessaging.outbox.healthcheck`` costs ~0.85s and ~60MB per
probe, against a 5s probe timeout under the pod CPU limit. ``settings.py``
takes its defaults from here, so the roles and the check agree.

The max age covers idle loops too: the relay touches the file after every
pass that did not raise, the consumers after every fetch iteration of all
four brokers, empty fetches included.
"""

from __future__ import annotations

import os
import sys
import time

DEFAULT_MAX_AGE = 180.0

# role -> (path env var, default path, max-age env var)
ROLES = {
    "relay": (
        "OUTBOX_RELAY_HEARTBEAT_PATH",
        "/tmp/forms-relay.heartbeat",
        "OUTBOX_RELAY_HEARTBEAT_MAX_AGE",
    ),
    "consume": (
        "CONSUMERS_HEARTBEAT_PATH",
        "/tmp/forms-consumers.heartbeat",
        "CONSUMERS_HEARTBEAT_MAX_AGE",
    ),
}


def path_for(role: str, env=os.environ) -> str:
    path_var, default, _ = ROLES[role]
    return env.get(path_var, default)


def max_age_for(role: str, env=os.environ) -> float:
    _, _, age_var = ROLES[role]
    return float(env.get(age_var, DEFAULT_MAX_AGE))


def is_fresh(path: str, max_age: float, now: float | None = None) -> bool:
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return False
    return (time.time() if now is None else now) - mtime <= max_age


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ROLES:
        print(f"usage: heartbeat.py {'|'.join(ROLES)}", file=sys.stderr)
        return 2
    role = argv[0]
    path, max_age = path_for(role), max_age_for(role)
    if is_fresh(path, max_age):
        return 0
    print(f"{role} heartbeat {path} missing or older than {max_age}s", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

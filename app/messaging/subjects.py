"""Single global subject-token registry for domain events.

Each domain registers its event classes against the token that the
relay will turn into the final NATS subject (``{OUTBOX_SUBJECT_PREFIX}.{token}``).
"""

from __future__ import annotations

_REGISTRY: dict[type, str] = {}


def register(event_cls: type, token: str) -> None:
    _REGISTRY[event_cls] = token


def subject_token_for(event_cls: type) -> str:
    try:
        return _REGISTRY[event_cls]
    except KeyError as exc:
        raise LookupError(
            f"No subject token registered for event class {event_cls.__name__}. "
            "Register it in your app's subjects module and ensure that "
            "module is imported in apps.py ready()."
        ) from exc


def registered_events() -> dict[type, str]:
    return dict(_REGISTRY)

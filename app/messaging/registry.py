from __future__ import annotations

from unimessaging.broker.registry import register_handler

from app import messaging_contract as contract
from .handlers.auth_events import AuthEventSubscriber
from .handlers.curriculum_events import CurriculumEventSubscriber
from .handlers.order_events import OrderEventSubscriber
from .handlers.recommendable_events import RecommendableEventSubscriber
from .handlers.users_child_events import UsersChildEventSubscriber


def _to_pattern(subject: str) -> str:
    """Convert NATS wildcards to fnmatch wildcards used by unimessaging registry."""
    return subject.replace(">", "*")


def register_handlers() -> None:
    """Wire messaging handlers for all external event subscriptions."""
    auth_subscriber = AuthEventSubscriber()
    curriculum_subscriber = CurriculumEventSubscriber()
    recommendable_subscriber = RecommendableEventSubscriber()
    users_child_subscriber = UsersChildEventSubscriber()
    order_subscriber = OrderEventSubscriber()

    register_handler("auth.UserRegistered", auth_subscriber.handle_message)

    for subject in contract.CURRICULUM_EVENT_SUBJECTS:
        register_handler(_to_pattern(subject), curriculum_subscriber.handle_message)

    for subject in contract.RECOMMENDABLE_SUBJECTS:
        register_handler(_to_pattern(subject), recommendable_subscriber.handle_message)

    for subject in contract.USERS_CHILD_SUBJECTS:
        register_handler(_to_pattern(subject), users_child_subscriber.handle_message)

    for subject in contract.ORDERS_EVENT_SUBJECTS:
        register_handler(_to_pattern(subject), order_subscriber.handle_message)

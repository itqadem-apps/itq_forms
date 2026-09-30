from __future__ import annotations

from unimessaging.broker.registry import register_handler

from app import messaging_contract as contract
from .handlers.auth_events import AuthEventSubscriber
from .handlers.external_reference_events import ExternalReferenceEventSubscriber
from .handlers.order_events import OrderEventSubscriber
from .handlers.recommendable_events import RecommendableEventSubscriber
from .handlers.taxonomy_events import TaxonomyCategoryEventSubscriber
from .handlers.users_child_events import UsersChildEventSubscriber


def register_handlers() -> None:
    """Wire messaging handlers for all external event subscriptions.

    Contract subjects are registered verbatim: the registry matches NATS-style, where
    ``*`` is one token and ``>`` the tail. Rewriting ``>`` to ``*`` (right for the old
    fnmatch registry) made ``courses.*`` miss every ``courses.<model>.<op>`` event, so
    the broker acked and dropped them from 2026-09-14 (estate task #157).
    """
    auth_subscriber = AuthEventSubscriber()
    external_reference_subscriber = ExternalReferenceEventSubscriber()
    recommendable_subscriber = RecommendableEventSubscriber()
    users_child_subscriber = UsersChildEventSubscriber()
    order_subscriber = OrderEventSubscriber()
    taxonomy_subscriber = TaxonomyCategoryEventSubscriber()

    register_handler("auth.UserRegistered", auth_subscriber.handle_message)

    for subject in contract.EXTERNAL_REFERENCE_EVENT_SUBJECTS:
        register_handler(subject, external_reference_subscriber.handle_message)

    for subject in contract.RECOMMENDABLE_SUBJECTS:
        register_handler(subject, recommendable_subscriber.handle_message)

    for subject in contract.USERS_CHILD_SUBJECTS:
        register_handler(subject, users_child_subscriber.handle_message)

    for subject in contract.ORDERS_EVENT_SUBJECTS:
        register_handler(subject, order_subscriber.handle_message)

    for subject in contract.TAXONOMY_CATEGORY_SUBJECTS:
        register_handler(subject, taxonomy_subscriber.handle_message)

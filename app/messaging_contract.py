from __future__ import annotations

import re

from unimessaging.broker.config import JetStreamConsumer

FORMS_STREAM_NAME = "FORMS"
FORMS_STREAM_SUBJECTS: list[str] = ["forms.>"]

RECOMMENDABLE_SUBJECTS: list[str] = [
    "courses.>",
    "videos.>",
    "articles.>",
    "reservations.>",
]
RECOMMENDABLE_CONSUMERS: list[JetStreamConsumer] = [
    JetStreamConsumer(
        label="recommendables",
        subject="courses.>",
        durable="forms-recommendables-courses-consumer",
    ),
    JetStreamConsumer(
        label="recommendables",
        subject="videos.>",
        durable="forms-recommendables-videos-consumer",
    ),
    JetStreamConsumer(
        label="recommendables",
        subject="articles.>",
        durable="forms-recommendables-articles-consumer",
    ),
    JetStreamConsumer(
        label="recommendables",
        subject="reservations.>",
        durable="forms-recommendables-reservations-consumer",
    ),
]

AUTH_CONSUMERS: list[JetStreamConsumer] = [
    JetStreamConsumer(
        label="auth",
        subject="auth.UserRegistered",
        durable="forms-auth-user-registered-consumer",
    )
]

CURRICULUM_EVENT_SUBJECTS: list[str] = [
    "*.curriculum_reference",
    "*.curriculum_enrollment",
]
CURRICULUM_EVENT_CONSUMER = JetStreamConsumer(
    label="curriculum",
    subject="*.curriculum_reference",
    durable="forms-curriculum-events-consumer",
)
CURRICULUM_EVENT_CONSUMERS: list[JetStreamConsumer] = [
    CURRICULUM_EVENT_CONSUMER,
    JetStreamConsumer(
        label="curriculum",
        subject="*.curriculum_enrollment",
        durable="forms-curriculum-events-consumer-enrollment",
    ),
]

USERS_CHILD_STREAM_NAME = "USERS"
USERS_CHILD_STREAM_SUBJECTS: list[str] = ["users.>"]
USERS_CHILD_SUBJECTS: list[str] = [
    "users.child.>",
    "users.child_guardian.>",
]

ORDERS_STREAM_NAME = "ORDERS"
ORDERS_STREAM_SUBJECTS: list[str] = ["orders.>"]
ORDERS_EVENT_SUBJECTS: list[str] = ["orders.order"]
ORDERS_EVENT_DURABLE_BASE = "forms-orders-order-consumer"


def recommendable_durable_name(subject: str) -> str:
    service = subject.split(".", 1)[0].strip().lower() or "consumer"
    return f"forms-recommendables-{service}-consumer"


def build_recommendable_consumers(subjects: list[str]) -> list[JetStreamConsumer]:
    return [
        JetStreamConsumer(
            label="recommendables",
            subject=subject,
            durable=recommendable_durable_name(subject),
        )
        for subject in subjects
    ]


def build_users_child_consumers(subjects: list[str]) -> list[JetStreamConsumer]:
    return [
        JetStreamConsumer(
            label="users",
            subject=subject,
            durable=f"forms-{re.sub(r'[^a-zA-Z0-9_-]+', '-', subject).strip('-')}-consumer",
        )
        for subject in subjects
    ]


def order_durable_name(subject: str, subjects: list[str]) -> str:
    if len(subjects) == 1:
        return ORDERS_EVENT_DURABLE_BASE
    suffix = re.sub(r"[^a-zA-Z0-9_-]+", "-", subject).strip("-")
    return f"{ORDERS_EVENT_DURABLE_BASE}-{suffix}"

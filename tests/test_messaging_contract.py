from __future__ import annotations

import pytest

from app import messaging_contract as contract


@pytest.fixture
def db():
    return None


def test_build_users_child_consumers_preserves_existing_durable_format():
    consumers = contract.build_users_child_consumers(
        ["users.child.>", "users.child_guardian.>"]
    )

    assert [consumer.durable for consumer in consumers] == [
        "forms-users-child-consumer",
        "forms-users-child_guardian-consumer",
    ]


def test_order_durable_name_uses_base_for_single_subject():
    assert (
        contract.order_durable_name("orders.order", ["orders.order"])
        == "forms-orders-order-consumer"
    )


def test_order_durable_name_adds_subject_suffix_for_multiple_subjects():
    assert (
        contract.order_durable_name(
            "orders.order.refund",
            ["orders.order", "orders.order.refund"],
        )
        == "forms-orders-order-consumer-orders-order-refund"
    )


def test_build_recommendable_consumers_uses_stable_durable_names():
    consumers = contract.build_recommendable_consumers(["courses.>", "reservations.>"])

    assert [(consumer.subject, consumer.durable) for consumer in consumers] == [
        ("courses.>", "forms-recommendables-courses-consumer"),
        ("reservations.>", "forms-recommendables-reservations-consumer"),
    ]

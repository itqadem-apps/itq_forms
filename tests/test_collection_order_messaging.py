import os

import django
from asgiref.sync import async_to_sync

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from survey_collections.order_messaging import handle_order_event
from surveys.models import Usage


def _meta(event_type: str) -> dict:
    return {
        "subject": "orders.order",
        "headers": {"event_type": event_type},
    }


def test_capture_grants_usage_per_survey_in_collection(user, collection, survey):
    collection.assessments.add(survey)

    async_to_sync(handle_order_event)(
        {
            "order": {
                "id": 701,
                "user_id": user.id,
                "payment_state": "CAPTURED",
                "lines": [
                    {
                        "sku": f"forms:Collection:{collection.id}",
                        "service_name": "forms",
                        "qty": 2,
                        "payment_state": "CAPTURED",
                    }
                ],
            }
        },
        _meta("OrderPaymentCaptured"),
    )

    usage = Usage.objects.get(
        user=user, survey=survey, collection=collection, order_id="701"
    )
    assert usage.usage_limit == 2
    assert usage.used_count == 0


def test_capture_skipped_when_collection_missing(user):
    async_to_sync(handle_order_event)(
        {
            "order": {
                "id": 702,
                "user_id": user.id,
                "payment_state": "CAPTURED",
                "lines": [
                    {
                        "sku": "forms:Collection:999999",
                        "service_name": "forms",
                        "qty": 1,
                        "payment_state": "CAPTURED",
                    }
                ],
            }
        },
        _meta("OrderPaymentCaptured"),
    )

    assert not Usage.objects.filter(order_id="702").exists()


def test_full_refund_revokes_collection_usages(user, collection, survey):
    collection.assessments.add(survey)
    Usage.objects.create(
        user=user,
        survey=survey,
        collection=collection,
        order_id="703",
        usage_limit=1,
        used_count=0,
    )

    async_to_sync(handle_order_event)(
        {
            "order": {
                "id": 703,
                "user_id": user.id,
                "payment_state": "REFUNDED",
                "lines": [
                    {
                        "sku": f"forms:Collection:{collection.id}",
                        "service_name": "forms",
                        "qty": 1,
                        "payment_state": "REFUNDED",
                    }
                ],
            }
        },
        _meta("OrderPaymentRefunded"),
    )

    assert not Usage.objects.filter(
        user=user, collection=collection, order_id="703"
    ).exists()


def test_line_refund_revokes_only_matching_collection_line(user, collection, survey):
    collection.assessments.add(survey)
    Usage.objects.create(
        user=user,
        survey=survey,
        collection=collection,
        order_id="704",
        usage_limit=1,
        used_count=0,
    )

    async_to_sync(handle_order_event)(
        {
            "order": {
                "id": 704,
                "user_id": user.id,
                "payment_state": "PARTIALLY_REFUNDED",
                "lines": [
                    {
                        "sku": f"forms:Collection:{collection.id}",
                        "service_name": "forms",
                        "qty": 1,
                        "payment_state": "REFUNDED",
                    }
                ],
            },
            "line": {
                "sku": f"forms:Collection:{collection.id}",
                "service_name": "forms",
                "qty": 1,
                "payment_state": "REFUNDED",
            },
        },
        _meta("OrderLinePaymentRefunded"),
    )

    assert not Usage.objects.filter(
        user=user, collection=collection, order_id="704"
    ).exists()


def test_capture_ignores_non_collection_skus(user, survey):
    async_to_sync(handle_order_event)(
        {
            "order": {
                "id": 705,
                "user_id": user.id,
                "payment_state": "CAPTURED",
                "lines": [
                    {
                        "sku": f"forms:Survey:{survey.id}",
                        "service_name": "forms",
                        "qty": 1,
                        "payment_state": "CAPTURED",
                    }
                ],
            }
        },
        _meta("OrderPaymentCaptured"),
    )

    assert not Usage.objects.filter(order_id="705").exists()

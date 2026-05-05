import os

import django
from asgiref.sync import async_to_sync

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from surveys.models import Usage
from surveys.order_messaging import handle_order_event
from surveys.usage_access import select_usage_to_consume, summarize_usage_rows


def _meta(event_type: str) -> dict:
    return {
        "subject": "orders.order",
        "headers": {"event_type": event_type},
    }


def test_order_payment_captured_creates_usage_for_forms_line(survey):
    async_to_sync(handle_order_event)(
        {
            "order": {
                "id": 101,
                "user_id": "kc-order-user-1",
                "payment_state": "CAPTURED",
                "lines": [
                    {
                        "sku": f"forms:Survey:{survey.id}",
                        "service_name": "forms",
                        "qty": 3,
                        "payment_state": "CAPTURED",
                    }
                ],
            }
        },
        _meta("OrderPaymentCaptured"),
    )

    usage = Usage.objects.get(user_id="kc-order-user-1", survey=survey, order_id="101")
    assert usage.usage_limit == 3
    assert usage.used_count == 0


def test_duplicate_capture_updates_limit_but_preserves_used_count(user, survey):
    usage = Usage.objects.create(
        user=user,
        survey=survey,
        order_id="202",
        usage_limit=1,
        used_count=1,
    )

    async_to_sync(handle_order_event)(
        {
            "order": {
                "id": 202,
                "user_id": user.id,
                "payment_state": "CAPTURED",
                "lines": [
                    {
                        "sku": f"forms:Survey:{survey.id}",
                        "service_name": "forms",
                        "qty": 4,
                        "payment_state": "CAPTURED",
                    }
                ],
            }
        },
        _meta("OrderPaymentCaptured"),
    )

    usage.refresh_from_db()
    assert usage.usage_limit == 4
    assert usage.used_count == 1


def test_full_refund_revokes_matching_forms_usages(user, survey):
    Usage.objects.create(user=user, survey=survey, order_id="303", usage_limit=2, used_count=0)

    async_to_sync(handle_order_event)(
        {
            "order": {
                "id": 303,
                "user_id": user.id,
                "payment_state": "REFUNDED",
                "lines": [
                    {
                        "sku": f"forms:Survey:{survey.id}",
                        "service_name": "forms",
                        "qty": 2,
                        "payment_state": "REFUNDED",
                    }
                ],
            }
        },
        _meta("OrderPaymentRefunded"),
    )

    assert not Usage.objects.filter(user=user, survey=survey, order_id="303").exists()


def test_line_refund_revokes_only_matching_forms_line(user, survey):
    Usage.objects.create(user=user, survey=survey, order_id="404", usage_limit=1, used_count=0)

    async_to_sync(handle_order_event)(
        {
            "order": {
                "id": 404,
                "user_id": user.id,
                "payment_state": "PARTIALLY_REFUNDED",
                "lines": [
                    {
                        "sku": f"forms:Survey:{survey.id}",
                        "service_name": "forms",
                        "qty": 1,
                        "payment_state": "REFUNDED",
                    }
                ],
            },
            "line": {
                "sku": f"forms:Survey:{survey.id}",
                "service_name": "forms",
                "qty": 1,
                "payment_state": "REFUNDED",
            },
        },
        _meta("OrderLinePaymentRefunded"),
    )

    assert not Usage.objects.filter(user=user, survey=survey, order_id="404").exists()


def test_usage_summary_and_consumption_support_multiple_orders(user, survey):
    usage_one = Usage.objects.create(
        user=user,
        survey=survey,
        order_id="501",
        usage_limit=1,
        used_count=1,
    )
    usage_two = Usage.objects.create(
        user=user,
        survey=survey,
        order_id="502",
        usage_limit=2,
        used_count=0,
    )

    usages = list(Usage.objects.filter(user=user, survey=survey).order_by("created_at", "id"))
    summary = summarize_usage_rows(usages)

    assert summary.total_used == 1
    assert summary.total_limit == 3
    assert select_usage_to_consume(usages) == usage_two
    assert usage_one != usage_two

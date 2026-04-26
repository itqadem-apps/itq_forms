from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations


def backfill_prices(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    Price = apps.get_model("surveys", "Price")

    prices = []
    for survey in Survey.objects.all():
        if survey.price is None:
            continue
        amount_cents = int((Decimal(str(survey.price)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        prices.append(
            Price(
                survey_id=survey.id,
                currency="EGP",
                amount_cents=amount_cents,
            )
        )
    if prices:
        Price.objects.bulk_create(prices)


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0012_alter_survey_survey_type_price"),
    ]

    operations = [
        migrations.RunPython(backfill_prices, migrations.RunPython.noop),
    ]

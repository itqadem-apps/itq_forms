"""estate:AD-17 — lock prices to one EGP row per parent.

Separate from 0005: on Postgres, ALTER TABLE in the same transaction as the
data migration's deletes fails on pending deferred-FK trigger events.
"""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("pricing", "0005_egp_only"),
    ]

    operations = [
        migrations.AlterField(
            model_name="price",
            name="currency",
            field=models.CharField(default="EGP", max_length=3),
        ),
        migrations.AddConstraint(
            model_name="price",
            constraint=models.CheckConstraint(condition=Q(currency="EGP"), name="price_currency_egp"),
        ),
        migrations.AddConstraint(
            model_name="price",
            constraint=models.UniqueConstraint(
                condition=Q(survey__isnull=False),
                fields=("survey", "currency"),
                name="price_one_per_survey_currency",
            ),
        ),
        migrations.AddConstraint(
            model_name="price",
            constraint=models.UniqueConstraint(
                condition=Q(collection__isnull=False),
                fields=("collection", "currency"),
                name="price_one_per_collection_currency",
            ),
        ),
    ]

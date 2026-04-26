"""
Rename surveys_price → pricing_price, add CheckConstraint, create Discount table.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pricing", "0002_migrate_collection_prices"),
        ("surveys", "0031_move_price_to_pricing"),
        ("survey_collections", "0007_remove_collectionprice"),
    ]

    operations = [
        # Rename the table
        migrations.RunSQL(
            sql='ALTER TABLE "surveys_price" RENAME TO "pricing_price";',
            reverse_sql='ALTER TABLE "pricing_price" RENAME TO "surveys_price";',
        ),
        # Add CheckConstraint: exactly one of survey/collection must be set
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "pricing_price" ADD CONSTRAINT "price_exactly_one_parent" '
                'CHECK (("survey_id" IS NOT NULL AND "collection_id" IS NULL) '
                'OR ("survey_id" IS NULL AND "collection_id" IS NOT NULL));'
            ),
            reverse_sql='ALTER TABLE "pricing_price" DROP CONSTRAINT IF EXISTS "price_exactly_one_parent";',
        ),
        # Create Discount table
        migrations.CreateModel(
            name="Discount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type", models.CharField(choices=[("percentage", "Percentage"), ("fixed_amount", "Fixed Amount")], max_length=16)),
                ("value", models.IntegerField(help_text="Percent (0-100) or cents, depending on type.")),
                ("starts_at", models.DateTimeField(blank=True, null=True)),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("code", models.CharField(blank=True, max_length=64, null=True)),
                ("max_redemptions", models.IntegerField(blank=True, null=True)),
                ("redemption_count", models.IntegerField(default=0)),
                ("price", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="discounts",
                    to="pricing.price",
                )),
            ],
        ),
    ]

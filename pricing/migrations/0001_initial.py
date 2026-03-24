"""
Claim the existing surveys_price table into the pricing app state.
Add nullable collection_id column, make survey_id nullable.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("surveys", "0030_inline_status_on_survey"),
        ("survey_collections", "0006_collectionprice_remove_price"),
    ]

    operations = [
        # ── State-only: register Price under pricing app ──────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Price",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("currency", models.CharField(max_length=3)),
                        ("amount_cents", models.IntegerField()),
                        ("compare_at_amount_cents", models.IntegerField(blank=True, null=True)),
                        ("survey", models.ForeignKey(
                            blank=True, null=True,
                            on_delete=django.db.models.deletion.CASCADE,
                            related_name="prices",
                            to="surveys.survey",
                        )),
                        ("collection", models.ForeignKey(
                            blank=True, null=True,
                            on_delete=django.db.models.deletion.CASCADE,
                            related_name="prices",
                            to="survey_collections.surveycollection",
                        )),
                    ],
                ),
            ],
            database_operations=[
                # Make survey_id nullable (it was NOT NULL before)
                migrations.RunSQL(
                    sql='ALTER TABLE "surveys_price" ALTER COLUMN "survey_id" DROP NOT NULL;',
                    reverse_sql='ALTER TABLE "surveys_price" ALTER COLUMN "survey_id" SET NOT NULL;',
                ),
                # Add collection_id column
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "surveys_price" ADD COLUMN "collection_id" bigint NULL '
                        'REFERENCES "survey_collections_surveycollection" ("id") '
                        'DEFERRABLE INITIALLY DEFERRED;'
                    ),
                    reverse_sql='ALTER TABLE "surveys_price" DROP COLUMN "collection_id";',
                ),
                # Index on collection_id
                migrations.RunSQL(
                    sql='CREATE INDEX "surveys_price_collection_id_idx" ON "surveys_price" ("collection_id");',
                    reverse_sql='DROP INDEX IF EXISTS "surveys_price_collection_id_idx";',
                ),
            ],
        ),
    ]

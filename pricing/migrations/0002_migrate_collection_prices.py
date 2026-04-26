"""
Copy CollectionPrice rows into the unified surveys_price table.
"""
from django.db import migrations


def copy_collection_prices(apps, schema_editor):
    """Copy rows from survey_collections_collectionprice into surveys_price."""
    db = schema_editor.connection.alias
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            'INSERT INTO "surveys_price" ("currency", "amount_cents", "compare_at_amount_cents", "survey_id", "collection_id") '
            'SELECT "currency", "amount_cents", "compare_at_amount_cents", NULL, "collection_id" '
            'FROM "survey_collections_collectionprice";'
        )


def reverse_copy(apps, schema_editor):
    """Remove rows that came from collections (survey_id IS NULL)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DELETE FROM "surveys_price" WHERE "survey_id" IS NULL;')


class Migration(migrations.Migration):

    dependencies = [
        ("pricing", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'INSERT INTO "surveys_price" ("currency", "amount_cents", "compare_at_amount_cents", "survey_id", "collection_id") '
                'SELECT "currency", "amount_cents", "compare_at_amount_cents", NULL, "collection_id" '
                'FROM "survey_collections_collectionprice";'
            ),
            reverse_sql='DELETE FROM "surveys_price" WHERE "survey_id" IS NULL;',
        ),
    ]

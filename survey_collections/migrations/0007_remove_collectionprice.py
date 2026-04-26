"""
Remove CollectionPrice from survey_collections state and drop its table.
Data has been migrated to the unified pricing_price table.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("survey_collections", "0006_collectionprice_remove_price"),
        ("pricing", "0002_migrate_collection_prices"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="CollectionPrice"),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='DROP TABLE IF EXISTS "survey_collections_collectionprice";',
                    reverse_sql=(
                        'CREATE TABLE "survey_collections_collectionprice" ('
                        '    "id" bigserial PRIMARY KEY,'
                        '    "currency" varchar(3) NOT NULL,'
                        '    "amount_cents" integer NOT NULL,'
                        '    "compare_at_amount_cents" integer NULL,'
                        '    "collection_id" bigint NOT NULL REFERENCES "survey_collections_surveycollection" ("id") DEFERRABLE INITIALLY DEFERRED'
                        ');'
                    ),
                ),
            ],
        ),
    ]

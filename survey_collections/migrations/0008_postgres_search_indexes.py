"""
Add GIN indexes for full-text search + trigram similarity
on SurveyCollection fields (title, description, short_description).
"""
from django.db import migrations


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("survey_collections", "0007_remove_collectionprice"),
        ("surveys", "0032_postgres_search_indexes"),  # pg_trgm created there
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'CREATE INDEX CONCURRENTLY IF NOT EXISTS "ix_collection_fts" '
                "ON \"survey_collections_surveycollection\" USING GIN ("
                "to_tsvector('simple', "
                "coalesce(\"title\", '') || ' ' || "
                "coalesce(\"description\", '') || ' ' || "
                "coalesce(\"short_description\", '')"
                "));"
            ),
            reverse_sql='DROP INDEX IF EXISTS "ix_collection_fts";',
        ),
        migrations.RunSQL(
            sql=(
                'CREATE INDEX CONCURRENTLY IF NOT EXISTS "ix_collection_trgm_title" '
                'ON "survey_collections_surveycollection" USING GIN ("title" gin_trgm_ops);'
            ),
            reverse_sql='DROP INDEX IF EXISTS "ix_collection_trgm_title";',
        ),
    ]

"""
Enable pg_trgm extension and add GIN indexes for full-text search + trigram similarity
on SurveyTranslation fields.
"""
from django.db import migrations
from django.contrib.postgres.operations import TrigramExtension


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("surveys", "0031_move_price_to_pricing"),
    ]

    operations = [
        TrigramExtension(),
        migrations.RunSQL(
            sql=(
                'CREATE INDEX CONCURRENTLY IF NOT EXISTS "ix_survey_tr_fts" '
                "ON \"surveys_surveytranslation\" USING GIN ("
                "to_tsvector('simple', "
                "coalesce(\"title\", '') || ' ' || "
                "coalesce(\"description\", '') || ' ' || "
                "coalesce(\"short_description\", '')"
                "));"
            ),
            reverse_sql='DROP INDEX IF EXISTS "ix_survey_tr_fts";',
        ),
        migrations.RunSQL(
            sql=(
                'CREATE INDEX CONCURRENTLY IF NOT EXISTS "ix_survey_tr_trgm_title" '
                'ON "surveys_surveytranslation" USING GIN ("title" gin_trgm_ops);'
            ),
            reverse_sql='DROP INDEX IF EXISTS "ix_survey_tr_trgm_title";',
        ),
    ]

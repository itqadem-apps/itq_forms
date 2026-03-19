"""
Ensure every SurveyCollection has a translation row, then drop the
translatable fields (title, description, short_description, slug, language)
from the SurveyCollection table. Move search indexes to the translation table.
"""
from django.db import migrations


def ensure_translations(apps, schema_editor):
    """Create a translation row for any collection that doesn't have one yet."""
    SurveyCollection = apps.get_model("survey_collections", "SurveyCollection")
    SurveyCollectionTranslation = apps.get_model(
        "survey_collections", "SurveyCollectionTranslation"
    )

    for c in SurveyCollection.objects.all():
        if not SurveyCollectionTranslation.objects.filter(collection_id=c.id).exists():
            SurveyCollectionTranslation.objects.create(
                collection_id=c.id,
                language=c.language or "ar",
                title=c.title,
                description=c.description,
                short_description=c.short_description,
                slug=c.slug,
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("survey_collections", "0008_postgres_search_indexes"),
    ]

    operations = [
        # 1. Ensure all collections have translations
        migrations.RunPython(ensure_translations, noop, atomic=True),

        # 2. Drop stale search indexes on columns about to be removed
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS "ix_collection_fts";',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS "ix_collection_trgm_title";',
            reverse_sql=migrations.RunSQL.noop,
        ),

        # 3. Remove translatable columns from the collection table
        migrations.RemoveField(model_name="surveycollection", name="title"),
        migrations.RemoveField(model_name="surveycollection", name="description"),
        migrations.RemoveField(model_name="surveycollection", name="short_description"),
        migrations.RemoveField(model_name="surveycollection", name="slug"),
        migrations.RemoveField(model_name="surveycollection", name="language"),

        # 4. Add search indexes on the translation table
        migrations.RunSQL(
            sql=(
                'CREATE INDEX CONCURRENTLY IF NOT EXISTS "ix_col_tr_fts" '
                "ON \"survey_collections_surveycollectiontranslation\" USING GIN ("
                "to_tsvector('simple', "
                "coalesce(\"title\", '') || ' ' || "
                "coalesce(\"description\", '') || ' ' || "
                "coalesce(\"short_description\", '')"
                "));"
            ),
            reverse_sql='DROP INDEX IF EXISTS "ix_col_tr_fts";',
        ),
        migrations.RunSQL(
            sql=(
                'CREATE INDEX CONCURRENTLY IF NOT EXISTS "ix_col_tr_trgm_title" '
                'ON "survey_collections_surveycollectiontranslation" USING GIN ("title" gin_trgm_ops);'
            ),
            reverse_sql='DROP INDEX IF EXISTS "ix_col_tr_trgm_title";',
        ),
    ]

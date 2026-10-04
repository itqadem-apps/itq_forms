from django.db import migrations, models

"""Make organization_id required (estate #168).

Every row carries an organisation since the 2026-10-04 ownership run. On a
database that still holds one without, SET NOT NULL fails and this migration
changes nothing: assign the owner first, don't add a default here.
"""


class Migration(migrations.Migration):

    dependencies = [
        ("survey_collections", "0014_surveycollection_cover_id_surveycollection_thumb_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="surveycollection",
            name="organization_id",
            field=models.UUIDField(
                db_index=True, verbose_name="Organization ID"
            ),
        ),
    ]

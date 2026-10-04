from django.db import migrations, models

"""Make organization_id required (estate #168).

Every row carries an organisation since the 2026-10-04 ownership run. On a
database that still holds one without, SET NOT NULL fails and this migration
changes nothing: assign the owner first, don't add a default here.
"""


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0044_move_unenrolled_surveys_to_ar"),
    ]

    operations = [
        migrations.AlterField(
            model_name="survey",
            name="organization_id",
            field=models.UUIDField(
                db_index=True, verbose_name="Organization ID"
            ),
        ),
    ]

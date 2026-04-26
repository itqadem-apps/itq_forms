from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("survey_collections", "0011_seo_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="surveycollection",
            name="organization_id",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="Organization ID",
            ),
        ),
    ]

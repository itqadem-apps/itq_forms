# Generated manually to persist assessment organization ownership for search events.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0033_seo_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey",
            name="organization_id",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="Organization ID",
            ),
        ),
    ]

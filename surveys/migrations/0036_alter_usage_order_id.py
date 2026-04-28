from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0035_backfill_organization_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usage",
            name="order_id",
            field=models.CharField(max_length=64),
        ),
    ]

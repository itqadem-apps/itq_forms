from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0055_report_routing_on_multi_select"),
    ]

    operations = [
        migrations.AddField(
            model_name="answerschemaoption",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

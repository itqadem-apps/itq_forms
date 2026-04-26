"""
Create CollectionPrice model and remove the price FloatField from SurveyCollection.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("survey_collections", "0005_backfill_surveycollectiontranslation"),
    ]

    operations = [
        migrations.CreateModel(
            name="CollectionPrice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("currency", models.CharField(max_length=3)),
                ("amount_cents", models.IntegerField()),
                ("compare_at_amount_cents", models.IntegerField(blank=True, null=True)),
                ("collection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="prices", to="survey_collections.surveycollection")),
            ],
        ),
        migrations.RemoveField(
            model_name="surveycollection",
            name="price",
        ),
    ]

"""
Create Recommendable model and replace the generic foreign key
(content_type + object_id) on Material with a ForeignKey to Recommendable.
"""
import django.db.models.deletion
from django.db import migrations, models
from django.utils.timezone import now


class Migration(migrations.Migration):

    dependencies = [
        ("recommendations", "0004_rename_recommendedmaterial_to_material"),
    ]

    operations = [
        migrations.CreateModel(
            name="Recommendable",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_service", models.CharField(max_length=255)),
                ("source_model", models.CharField(max_length=255)),
                ("source_id", models.CharField(max_length=255)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(blank=True, default=now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["source_service", "source_model", "source_id"],
                        name="uq_recommendable_source",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="material",
            name="recommendable",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="materials",
                to="recommendations.recommendable",
                null=True,
            ),
            preserve_default=False,
        ),
        migrations.RemoveField(
            model_name="material",
            name="content_type",
        ),
        migrations.RemoveField(
            model_name="material",
            name="object_id",
        ),
        migrations.AlterField(
            model_name="material",
            name="recommendable",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="materials",
                to="recommendations.recommendable",
            ),
        ),
    ]

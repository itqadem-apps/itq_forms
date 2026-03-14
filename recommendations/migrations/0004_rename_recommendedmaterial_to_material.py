"""
Rename RecommendedMaterial model to Material and update its database table.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recommendations", "0003_remove_translatable_fields"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="RecommendedMaterial",
            new_name="Material",
        ),
        migrations.AlterModelTable(
            name="material",
            table=None,  # Django default: recommendations_material
        ),
        migrations.AlterField(
            model_name="material",
            name="action",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="materials",
                to="recommendations.action",
            ),
        ),
    ]

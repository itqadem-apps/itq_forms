"""
Rename category tables from surveys_ prefix to taxonomy_ prefix.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("taxonomy", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelTable(
            name="category",
            table=None,
        ),
        migrations.AlterModelTable(
            name="categorytranslation",
            table=None,
        ),
    ]

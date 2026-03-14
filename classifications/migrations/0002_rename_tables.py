"""
Rename classification tables from surveys_ prefix to classifications_ prefix.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("classifications", "0001_initial"),
        ("surveys", "0023_fix_classification_fk_state"),
    ]

    operations = [
        migrations.AlterModelTable(
            name="classification",
            table=None,  # revert to Django default: classifications_classification
        ),
        migrations.AlterModelTable(
            name="classificationtranslation",
            table=None,  # revert to Django default: classifications_classificationtranslation
        ),
    ]

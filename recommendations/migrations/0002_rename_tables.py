"""
Rename recommendation tables from surveys_ prefix to recommendations_ prefix.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("recommendations", "0001_initial"),
        ("surveys", "0024_move_recommendations_to_own_app"),
    ]

    operations = [
        migrations.AlterModelTable(
            name="recommendation",
            table=None,  # revert to Django default: recommendations_recommendation
        ),
        migrations.AlterModelTable(
            name="recommendationtranslation",
            table=None,  # revert to Django default: recommendations_recommendationtranslation
        ),
        migrations.AlterModelTable(
            name="action",
            table=None,  # revert to Django default: recommendations_action
        ),
        migrations.AlterModelTable(
            name="actiontranslation",
            table=None,  # revert to Django default: recommendations_actiontranslation
        ),
        migrations.AlterModelTable(
            name="recommendedmaterial",
            table=None,  # revert to Django default: recommendations_recommendedmaterial
        ),
    ]

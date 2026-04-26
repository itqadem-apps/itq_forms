"""
Remove Recommendation, RecommendationTranslation, Action, ActionTranslation,
and RecommendedMaterial from surveys app state.
The actual DB tables remain unchanged — the recommendations app now owns them.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0023_fix_classification_fk_state"),
        ("recommendations", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # Delete translation/child models first, then parents
                migrations.DeleteModel(name="RecommendationTranslation"),
                migrations.DeleteModel(name="RecommendedMaterial"),
                migrations.DeleteModel(name="ActionTranslation"),
                migrations.DeleteModel(name="Recommendation"),
                migrations.DeleteModel(name="Action"),
            ],
            database_operations=[],
        ),
    ]

"""
Remove Classification and ClassificationTranslation from surveys app state.
Update AnswerSchemaOption FK to point to classifications.Classification.
The actual DB tables remain unchanged — the classifications app now owns them.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0020_survey_enable_anti_cheat"),
        ("surveys", "0018_unimessaging_outbox"),
        ("classifications", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # Update FK before deleting the model from this app's state
                migrations.AlterField(
                    model_name="answerschemaoption",
                    name="classification",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="classifications.classification",
                    ),
                ),
                migrations.DeleteModel(name="ClassificationTranslation"),
                migrations.DeleteModel(name="Classification"),
            ],
            database_operations=[],
        ),
    ]

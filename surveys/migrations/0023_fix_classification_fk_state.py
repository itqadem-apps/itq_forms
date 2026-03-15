"""
Fix AnswerSchemaOption.classification FK state to point to classifications app.
No DB changes — just updates Django's internal migration state.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0022_remove_unimessagingoutbox_idx_outbox_pending_and_more"),
        ("classifications", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
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
            ],
            database_operations=[],
        ),
    ]

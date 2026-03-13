"""
Fix stale lazy references to surveys.classification in migration state.
The user_surveys models now reference user_surveys.UserClassification (changed in 0007),
but old migrations (0001, 0002) still register lazy refs to surveys.classification
which no longer exists after classifications app extraction.
No DB changes — state-only fix.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_surveys", "0020_termination_reason"),
        ("classifications", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # Re-state the M2M field to clear the stale lazy ref from 0002
                migrations.AlterField(
                    model_name="usersurvey",
                    name="classifications",
                    field=models.ManyToManyField(
                        through="user_surveys.UserSurveyClassification",
                        to="user_surveys.userclassification",
                    ),
                ),
                # Re-state the through-model FK to clear the stale lazy ref from 0001
                migrations.AlterField(
                    model_name="usersurveyclassification",
                    name="classification",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="user_surveys.userclassification",
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]

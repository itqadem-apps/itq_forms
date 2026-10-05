"""Make AnswerSchema.section and AnswerSchemaOption.section nullable (forms:AD-9, story survey-flow 1.3).

Schema only: DROP NOT NULL on two columns. No row is read or written. `on_delete` moves from
CASCADE to SET_NULL, which Django enforces in Python, so the database constraint is unchanged.
Reversal: migrating back to 0045 restores NOT NULL, which fails while any row holds a null
section — re-point those rows to a section first.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0045_organization_id_required"),
    ]

    operations = [
        migrations.AlterField(
            model_name="answerschema",
            name="section",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="surveys.section"
            ),
        ),
        migrations.AlterField(
            model_name="answerschemaoption",
            name="section",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="surveys.section"
            ),
        ),
    ]

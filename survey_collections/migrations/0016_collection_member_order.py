"""A collection's members get an order (intake report #128, story curricula-order 1.1).

The plain M2M's table is adopted as `CollectionMembership` in state only, so no
row is copied or dropped; the one database change is the `order` column. Each
collection's members are then numbered in their link order, which is the order
they were read in before this release.
"""

import django.db.models.deletion
from django.db import migrations, models


def seed_order(apps, schema_editor):
    Membership = apps.get_model("survey_collections", "CollectionMembership")
    rows = list(Membership.objects.order_by("surveycollection_id", "id"))
    position = {}
    for row in rows:
        row.order = position.get(row.surveycollection_id, 0)
        position[row.surveycollection_id] = row.order + 1
    Membership.objects.bulk_update(rows, ["order"], batch_size=1000)


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0001_initial"),
        ("survey_collections", "0015_organization_id_required"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="CollectionMembership",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("surveycollection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="survey_collections.surveycollection")),
                        ("survey", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="collection_memberships", to="surveys.survey")),
                    ],
                    options={
                        "db_table": "survey_collections_surveycollection_assessments",
                        "unique_together": {("surveycollection", "survey")},
                    },
                ),
                migrations.AlterField(
                    model_name="surveycollection",
                    name="assessments",
                    field=models.ManyToManyField(blank=True, help_text="Assessments included in this collection.", related_name="collections", through="survey_collections.CollectionMembership", to="surveys.survey"),
                ),
            ],
        ),
        migrations.AddField(
            model_name="collectionmembership",
            name="order",
            field=models.PositiveIntegerField(default=0, db_default=0),
        ),
        migrations.RunPython(seed_order, migrations.RunPython.noop),
    ]

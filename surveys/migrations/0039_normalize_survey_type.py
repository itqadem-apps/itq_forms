from django.db import migrations

#: `survey_type` is a plain CharField with `choices`, and Django does not enforce
#: choices at the database level — so writers that never ran the model's
#: full_clean() left values no code path recognises. Every one of them is a form:
#: `forms` is the route slug leaking into the column, `smart_form` a name from an
#: older editor. Both are invisible in the admin (the Forms tab resolves the slug
#: to the singular `form`, which matches nothing) and undeletable through GraphQL
#: (`app.permissions.PERMISSION_MAP[survey_type]` raises KeyError inside
#: `check_permission`, before the mutation body runs). Renaming restores both.
STRAY_TO_CANONICAL = {
    "forms": "form",
    "smart_form": "form",
}


def normalize(apps, schema_editor):
    Survey = apps.get_model("surveys", "Survey")
    for stray, canonical in STRAY_TO_CANONICAL.items():
        Survey.objects.filter(survey_type=stray).update(survey_type=canonical)


def reverse(apps, schema_editor):
    # Not reversible in any meaningful sense: rows that were `forms` and rows that
    # were `smart_form` are indistinguishable once both read `form`, and neither
    # value was ever valid. A no-op so the migration can still be unapplied.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0038_close_option_order_holes"),
    ]

    operations = [
        migrations.RunPython(normalize, reverse),
    ]

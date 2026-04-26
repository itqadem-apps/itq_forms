"""
Backfill path_text on all categories and add English translations.

Since all current categories are flat roots (no parent-child nesting),
path_text is simply set to the category name.
"""
from django.db import migrations


# (category_id, path_text, english_name, english_slug)
CATEGORIES = [
    ("cc763bb8-3dab-4aae-b38a-59ee1dbbc138", "Autism", "Autism", "autism"),
    ("a5dc7ac0-c3dc-4ce9-9d89-bd4c673719e1", "Autism Spectrum Disorder", "Autism Spectrum Disorder", "autism-spectrum-disorder"),
    ("529a94d8-f122-4127-bb65-50f25d21515a", "Developmental Disabilities", "Developmental Disabilities", "developmental-disabilities"),
    ("9a9b9b90-2f26-4af9-a34d-09ae6c02a329", "Interventions & Therapeutic Programs", "Interventions & Therapeutic Programs", "interventions-therapeutic-programs"),
    ("394d7935-8dae-4db9-a950-64561e1bba07", "Inclusive Education", "Inclusive Education", "inclusive-education"),
    ("5260fef2-69b8-4dc4-8204-2c37fddbb6e3", "Professional Development", "Professional Development", "professional-development"),
    ("1406615c-5591-45fd-a1ac-2811c90c5104", "Hyperlexia", "Hyperlexia", "hyperlexia"),
]


def backfill(apps, schema_editor):
    Category = apps.get_model("taxonomy", "Category")
    CategoryTranslation = apps.get_model("taxonomy", "CategoryTranslation")

    for cat_id, path_text, en_name, en_slug in CATEGORIES:
        updated = Category.objects.filter(category_id=cat_id).update(path_text=path_text)
        if updated:
            CategoryTranslation.objects.get_or_create(
                category_id=cat_id,
                language="en",
                defaults={"name": en_name, "slug": en_slug},
            )


def reverse_backfill(apps, schema_editor):
    Category = apps.get_model("taxonomy", "Category")
    CategoryTranslation = apps.get_model("taxonomy", "CategoryTranslation")

    cat_ids = [row[0] for row in CATEGORIES]
    Category.objects.filter(category_id__in=cat_ids).update(path_text=None)
    CategoryTranslation.objects.filter(category_id__in=cat_ids, language="en").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("taxonomy", "0002_rename_tables"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]

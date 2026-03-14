from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0026_remove_survey_translatable_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="survey",
            name="price",
        ),
    ]

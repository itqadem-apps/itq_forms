from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("user_surveys", "0003_usersurvey_collection"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="usersurvey",
            name="progress",
        ),
    ]

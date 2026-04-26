"""
Remove Price from surveys app state (it now lives in pricing).
No database changes — the table is still surveys_price.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0030_inline_status_on_survey"),
        ("pricing", "0002_migrate_collection_prices"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="Price"),
            ],
            database_operations=[],
        ),
    ]

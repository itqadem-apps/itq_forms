from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0017_backfill_translations"),
    ]

    operations = [
        migrations.CreateModel(
            name="UnimessagingOutbox",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("aggregate_type", models.TextField()),
                ("aggregate_id", models.TextField()),
                ("event_type", models.TextField()),
                ("payload", models.JSONField()),
                ("headers", models.JSONField(default=dict)),
                ("status", models.TextField(db_index=True, default="PENDING")),
                ("retries", models.IntegerField(default=0)),
                ("available_at", models.DateTimeField(auto_now_add=True)),
                ("occurred_at", models.DateTimeField()),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, null=True)),
            ],
            options={
                "db_table": "outbox",
            },
        ),
        migrations.AddIndex(
            model_name="unimessagingoutbox",
            index=models.Index(
                fields=["available_at"],
                name="idx_outbox_pending",
                condition=models.Q(status="PENDING"),
            ),
        ),
    ]

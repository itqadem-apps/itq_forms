from uuid import uuid4

from django.db import models

from .action import Action


class ActionTranslation(models.Model):
    class Meta:
        db_table = "surveys_actiontranslation"
        constraints = [
            models.UniqueConstraint(fields=["action", "language"], name="uq_action_language"),
        ]
        indexes = [
            models.Index(fields=["action", "language"], name="ix_action_tr_action_lang"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.action_id}:{self.language}"

from uuid import uuid4

from django.db import models

from .section import Section


class SectionTranslation(models.Model):
    class Meta:
        db_table = "surveys_sectiontranslation"
        constraints = [
            models.UniqueConstraint(fields=["section", "language"], name="uq_section_language"),
        ]
        indexes = [
            models.Index(fields=["section", "language"], name="ix_section_tr_section_lang"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.section_id}:{self.language}"

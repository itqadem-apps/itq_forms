from uuid import uuid4

from django.db import models

from .survey import Survey


class SurveyTranslation(models.Model):
    class Meta:
        db_table = "surveys_surveytranslation"
        constraints = [
            models.UniqueConstraint(fields=["survey", "language"], name="uq_survey_language"),
        ]
        indexes = [
            models.Index(fields=["survey", "language"], name="ix_survey_tr_survey_lang"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    short_description = models.CharField(max_length=300, null=True, blank=True)
    slug = models.CharField(max_length=255, null=True, blank=True)
    seo = models.JSONField(null=True, blank=True)

    def save(self, *args, **kwargs):
        """Claim the survey's primary language for the first language authored.

        `forms:AD-1` stores the primary on `Survey.primary_language` instead of
        deriving it. A null primary sends the snapshot's legacy-column fallback
        to ``"default"`` — filing body text under a key no learner reads. So the
        first translation saved onto a survey whose column is null sets it, and
        no later one moves it: the value's whole purpose is to not move, because
        enrolment snapshots freeze it per learner.

        The column has an ORM default (``"ar"`` since 0043), so a survey created
        through the ORM is never null and this claim does not fire;
        `create_survey` sets the primary from its translations instead. The
        claim remains for a survey whose column was explicitly left null.

        Only `save` claims it. `bulk_create` does not call this, so a bulk
        import must set `Survey.primary_language` itself.
        """
        super().save(*args, **kwargs)
        if self.language and not self.survey.primary_language:
            Survey.objects.filter(pk=self.survey_id, primary_language__isnull=True).update(
                primary_language=self.language
            )
            self.survey.primary_language = self.language

    def __str__(self) -> str:
        return f"{self.survey_id}:{self.language}"

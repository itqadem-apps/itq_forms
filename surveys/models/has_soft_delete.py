from django.db import models


class LiveManager(models.Manager):
    """The default manager of a soft-deletable builder row: live rows only (`forms:AD-21`).

    Being the default, it also backs every related manager (`survey.sections`,
    `section.questions`, `schema.options`). It is never named `base_manager_name`, so forward
    foreign keys and the delete collector keep seeing every row; `all_objects` is the explicit
    way to see deleted rows.
    """

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class LiveQuestionManager(models.Manager):
    """`AnswerSchema` has no `deleted_at` of its own: it is live while its question is."""

    def get_queryset(self):
        return super().get_queryset().filter(question__deleted_at__isnull=True)


class HasSoftDelete(models.Model):
    class Meta:
        abstract = True

    deleted_at = models.DateTimeField(blank=True, null=True)

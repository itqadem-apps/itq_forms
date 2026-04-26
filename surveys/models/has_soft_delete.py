from django.db import models


class HasSoftDelete(models.Model):
    class Meta:
        abstract = True

    deleted_at = models.DateTimeField(blank=True, null=True)

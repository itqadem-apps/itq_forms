from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .action import Action


class RecommendedMaterial(models.Model):
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name="recommended_materials")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey()

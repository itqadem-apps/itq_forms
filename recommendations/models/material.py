from django.db import models

from .action import Action
from .recommendable import Recommendable


class Material(models.Model):
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name="materials")
    recommendable = models.ForeignKey(Recommendable, on_delete=models.CASCADE, related_name="materials")

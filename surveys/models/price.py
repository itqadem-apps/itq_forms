from django.db import models

from .survey import Survey


class Price(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="prices")
    currency = models.CharField(max_length=3)
    amount_cents = models.IntegerField()
    compare_at_amount_cents = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.currency} {self.amount_cents}"

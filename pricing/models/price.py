from django.db import models
from django.db.models import Q


class Price(models.Model):
    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(survey__isnull=False, collection__isnull=True)
                    | Q(survey__isnull=True, collection__isnull=False)
                ),
                name="price_exactly_one_parent",
            ),
        ]

    survey = models.ForeignKey(
        "surveys.Survey",
        on_delete=models.CASCADE,
        related_name="prices",
        null=True,
        blank=True,
    )
    collection = models.ForeignKey(
        "survey_collections.SurveyCollection",
        on_delete=models.CASCADE,
        related_name="prices",
        null=True,
        blank=True,
    )
    currency = models.CharField(max_length=3)
    amount_cents = models.IntegerField()
    compare_at_amount_cents = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.currency} {self.amount_cents}"

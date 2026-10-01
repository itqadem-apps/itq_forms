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
            # estate:AD-17: one price per parent, in EGP.
            models.CheckConstraint(condition=Q(currency="EGP"), name="price_currency_egp"),
            models.UniqueConstraint(
                fields=["survey", "currency"],
                condition=Q(survey__isnull=False),
                name="price_one_per_survey_currency",
            ),
            models.UniqueConstraint(
                fields=["collection", "currency"],
                condition=Q(collection__isnull=False),
                name="price_one_per_collection_currency",
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
    currency = models.CharField(max_length=3, default="EGP")
    amount_cents = models.IntegerField()
    compare_at_amount_cents = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.currency} {self.amount_cents}"

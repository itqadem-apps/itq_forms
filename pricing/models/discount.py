from django.db import models


class Discount(models.Model):
    DISCOUNT_TYPE_PERCENTAGE = "percentage"
    DISCOUNT_TYPE_FIXED_AMOUNT = "fixed_amount"
    DISCOUNT_TYPE_CHOICES = (
        (DISCOUNT_TYPE_PERCENTAGE, "Percentage"),
        (DISCOUNT_TYPE_FIXED_AMOUNT, "Fixed Amount"),
    )

    price = models.ForeignKey(
        "pricing.Price",
        on_delete=models.CASCADE,
        related_name="discounts",
    )
    type = models.CharField(max_length=16, choices=DISCOUNT_TYPE_CHOICES)
    value = models.IntegerField(help_text="Percent (0-100) or cents, depending on type.")
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    max_redemptions = models.IntegerField(null=True, blank=True)
    redemption_count = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.type} {self.value} on price {self.price_id}"

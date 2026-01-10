from uuid import uuid4

from django.db import models


class Category(models.Model):
    class Meta:
        db_table = "surveys_category"
        constraints = [
            models.UniqueConstraint(
                fields=["tree_id", "category_id"],
                name="uq_category_tree_category_id",
            ),
        ]
        indexes = [
            models.Index(fields=["tree_id", "category_id"], name="ix_category_tree_category_id"),
        ]

    category_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tree_id = models.UUIDField()
    name = models.CharField(max_length=255, null=True, blank=True)
    path_text = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name or str(self.category_id)


class CategoryTranslation(models.Model):
    class Meta:
        db_table = "surveys_categorytranslation"
        constraints = [
            models.UniqueConstraint(fields=["category", "language"], name="uq_category_language"),
        ]
        indexes = [
            models.Index(
                fields=["category", "language"],
                name="ix_cat_tr_cat_lang",
            ),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    name = models.TextField(null=True, blank=True)
    slug = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.category_id}:{self.language}"

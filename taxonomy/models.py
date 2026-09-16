from uuid import uuid4

from django.db import models


class Category(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tree_id", "category_id"],
                name="uq_category_tree_category_id",
            ),
        ]
        indexes = [
            models.Index(fields=["tree_id", "category_id"], name="ix_category_tree_category_id"),
            models.Index(fields=["path_text"], name="ix_category_path_text"),
        ]

    category_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tree_id = models.UUIDField()
    name = models.CharField(max_length=255, null=True, blank=True)
    path_text = models.TextField(null=True, blank=True)

    # Event-time watermark (estate:AD-15). One durable now carries every
    # operation on a category, so ordering between operations is no longer
    # guaranteed by separate consumers; the projection advances only on a
    # strictly-newer `occurred_at`. Null means "never projected from an event"
    # — the legacy rows migration 0003 seeded are in that state until they are
    # reconciled.
    occurred_at = models.DateTimeField(null=True, blank=True)

    # Tombstone rather than a row delete. A delete that arrives before its
    # create must still suppress the later create (estate:AD-15), which a
    # missing row cannot do — an absent row is indistinguishable from "not yet
    # seen". Reads must exclude tombstones; see `live()`.
    deleted_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def live(cls, tree_id=None):
        """Rows a reader should see: not tombstoned, optionally one tree."""
        qs = cls.objects.filter(deleted_at__isnull=True)
        if tree_id is not None:
            qs = qs.filter(tree_id=tree_id)
        return qs

    def __str__(self) -> str:
        return self.name or str(self.category_id)


class CategoryTranslation(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["category", "language"], name="uq_category_language"),
        ]
        indexes = [
            models.Index(
                fields=["category", "language"],
                name="ix_cat_tr_cat_lang",
            ),
            models.Index(fields=["slug"], name="ix_cat_tr_slug"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    name = models.TextField(null=True, blank=True)
    slug = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.category_id}:{self.language}"


class DeferredCategoryEvent(models.Model):
    """A CategoryUpdated that arrived before the create it depends on.

    `CategoryUpdated` carries `path` but not `tree_id`, so on its own it cannot
    be projected: we would not know whether the category belongs to the tree we
    project, and writing a tree-less row would surface a broken category to
    readers. itq_courses drops such an event
    (`interface/messaging/handlers/category_events.py`, "likely out-of-order
    replay, skipping"), which loses a rename for good when replay delivers the
    update first.

    Parking it instead keeps the rename: when the matching `CategoryCreated`
    arrives and passes the tree filter, the parked payload is applied on top if
    its `occurred_at` is newer. Rows are deleted once applied or once judged
    stale, so this table stays near-empty in steady state.
    """

    class Meta:
        indexes = [
            models.Index(fields=["category_id"], name="ix_deferred_cat_id"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    category_id = models.UUIDField()
    occurred_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"deferred:{self.category_id}@{self.occurred_at}"

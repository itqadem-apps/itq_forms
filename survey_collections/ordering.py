from django.db.models import OuterRef, QuerySet, Subquery

from survey_collections.models import CollectionMembership


def order_by_collection(qs: QuerySet, collection_id: int) -> QuerySet:
    """Surveys in the order their collection stores (report #128)."""
    position = CollectionMembership.objects.filter(
        surveycollection_id=collection_id, survey_id=OuterRef("pk")
    ).values("order")[:1]
    return qs.annotate(collection_order=Subquery(position)).order_by("collection_order", "pk")

from __future__ import annotations

from typing import Optional
from uuid import UUID

from django.db import models
from django.utils.timezone import now
from pkg_media import UploadRecord as Record


class UploadRecord(models.Model):
    """Who started a browser upload through forms, for what, and the asset it
    was attached as (`pkg_media.service_uploads`).

    The only proof that an asset id came from forms: media treats every
    service credential as the owner of every asset, so an id column written
    with a bare id from a browser would let forms' resolve endpoints serve
    any asset in media. Ids attach through `claim_upload`, once."""

    session_id = models.UUIDField(primary_key=True)
    owner = models.CharField(max_length=128)
    profile = models.CharField(max_length=64)
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=now)
    attached_asset_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "media_upload_records"
        indexes = [models.Index(fields=["owner", "attached_asset_id"], name="media_upload_owner_asset")]

    def to_record(self) -> Record:
        return Record(
            session_id=self.session_id,
            owner=self.owner,
            profile=self.profile,
            context=dict(self.context or {}),
            created_at=self.created_at,
            attached_asset_id=self.attached_asset_id,
        )


class DjangoUploadStore:
    """`UploadSessionStore` over `UploadRecord`. `mark_attached` is one
    conditional UPDATE, so a session attaches once even under a race; call it
    inside the caller's transaction."""

    def save(self, record: Record) -> None:
        UploadRecord.objects.create(
            session_id=record.session_id,
            owner=record.owner,
            profile=record.profile,
            context=dict(record.context),
            created_at=record.created_at,
            attached_asset_id=record.attached_asset_id,
        )

    def get(self, session_id: UUID) -> Optional[Record]:
        row = UploadRecord.objects.filter(pk=session_id).first()
        return row.to_record() if row is not None else None

    def mark_attached(self, session_id: UUID, asset_id: UUID) -> bool:
        return (
            UploadRecord.objects
            .filter(pk=session_id, attached_asset_id__isnull=True)
            .update(attached_asset_id=asset_id)
            == 1
        )

from django.db import models

from .user_action import UserAction
from .user_survey import UserSurvey


class UserMaterial(models.Model):
    """A catalog entry pinned to a score band, snapshotted at enrolment.

    Freeze-versus-live ruling (the rest of the contract is on
    ``user_surveys.services.create_survey_snapshot``):

    * **Which** materials a learner gets is frozen. The rows are written once,
      in the enrolment snapshot, from ``Action.materials`` as it stood then.
      An admin who re-pins a band afterwards does not reach anyone already
      enrolled — the same rule every other ``User*`` row follows.
    * **What each material renders as** is live. ``Recommendable.data`` is
      maintained by the event consumer, not by an admin, so a course that is
      retitled or moved would otherwise leave the learner holding a wrong title
      and a dead link forever. ``payload`` reads through the FK.
    * **A deleted catalog row leaves the card standing.** The FK is
      ``SET_NULL`` and the frozen ``data`` copy takes over, so the learner keeps
      what they were given. An unpublish arrives only as a changed payload —
      nothing here interprets a status field — so both cases behave the same.

    ``source_service`` / ``source_model`` / ``source_id`` are the catalog's
    unique key and are immutable upstream, so the frozen copy is also the
    current value; they are what a client routes on once ``recommendable`` is
    gone.
    """

    class Meta:
        ordering = ["id"]

    # int4, pointing at an int8 primary key (`recommendations.Material.id`),
    # and the same is true of the seven sibling `User*.origin_id` columns.
    # Asked on 2026-09-24 whether to widen them: **no, not now** — and if
    # ever, all eight together. The verdict, the reasoning and the threshold
    # that reverses it are in `tools/audit_snapshot_origin_id_headroom.sql`,
    # which also measures both sides of it. The short form: widening the
    # column alone would not lift the ceiling, because `origin_id` is served
    # as GraphQL `Int` and the spec fixes that at 32 bits — it would only move
    # the failure from a refused INSERT at enrolment to a serialisation error
    # on the learner's result page. And what spends the range is authoring,
    # not enrolment: every one of the eight points at an admin-authored row,
    # while the per-learner tables' own keys are already int8.
    origin_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, related_name="materials")
    user_action = models.ForeignKey(UserAction, on_delete=models.CASCADE, related_name="materials")
    recommendable = models.ForeignKey(
        "recommendations.Recommendable",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_materials",
    )
    source_service = models.CharField(max_length=255, blank=True, default="")
    source_model = models.CharField(max_length=255, blank=True, default="")
    source_id = models.CharField(max_length=255, blank=True, default="")
    data = models.JSONField(default=dict, blank=True)

    @property
    def payload(self) -> dict:
        """The live catalog payload, falling back to the frozen copy."""
        if self.recommendable_id is not None and self.recommendable is not None:
            return self.recommendable.data
        return self.data

    def __str__(self):
        return f"{self.source_service}:{self.source_model}:{self.source_id}"

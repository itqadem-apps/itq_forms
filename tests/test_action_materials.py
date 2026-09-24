"""Materials pinned to a score band reach the learner's result.

`itq_forms` models a complete recommendation chain — an `Action` is a score
band, a `Material` pins catalog entries to it, and a `Recommendable` is a
cross-service catalog row kept current by the event consumer. Until now the
chain stopped at the admin boundary: `UserAction` snapshotted the two limits
and a translations blob and nothing else, so a matched band delivered nothing.

The ruling these tests pin (full text on `UserMaterial`):

* the *set* of materials is frozen at enrolment, like every other `User*` row;
* each material's *payload* is live, read through the FK to `Recommendable`,
  because the catalog is maintained by events rather than by an admin;
* deleting the catalog row leaves the card standing on the frozen copy.
"""

import pytest
from django.utils.timezone import now

from recommendations.models import Action, ActionTranslation, Material, Recommendable
from user_surveys.models import UserAction, UserMaterial
from user_surveys.services import enroll_user_in_assessment, evaluate_assessment


RESULTS_QUERY = """
query Results($input: UserSurveysListInput!) {
  userSurvey(userSurveysListInput: $input) {
    items {
      id
      score
      actionId
      actions {
        id
        originId
        lowerLimit
        upperLimit
        materials { id originId sourceService sourceModel sourceId data }
      }
    }
  }
}
"""


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user):
        self.request = None
        self.identity = _Identity(user)
        self.auth_context = None
        self.currency = None


def _results(user, user_survey):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        RESULTS_QUERY,
        variable_values={
            "input": {"limit": 1, "offset": 0, "filters": {"id": user_survey.id}, "sort": None}
        },
        context_value=_Context(user),
    )
    assert result.errors is None, result.errors
    return result.data["userSurvey"]["items"][0]


def _recommendable(source_id="101", title="Intro to Statistics", service="courses"):
    return Recommendable.objects.create(
        source_service=service,
        source_model="Course",
        source_id=source_id,
        data={"title": title, "slug": f"course-{source_id}"},
    )


@pytest.fixture
def scored_survey(survey, section, question, options):
    """A survey that scores and acts, with one band covering 36-45."""
    survey.use_score = True
    survey.use_actions = True
    survey.save(update_fields=["use_score", "use_actions"])
    return survey


@pytest.fixture
def band(scored_survey):
    action = Action.objects.create(survey=scored_survey, lower_limit=36, upper_limit=45)
    ActionTranslation.objects.create(
        action=action, language="en", title="Strong", description="Well done"
    )
    return action


def _enrol_and_score(user, survey, options, total):
    """Enrol, answer with options summing to *total*, and evaluate."""
    from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion

    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    user_survey.use_score = True
    user_survey.use_actions = True
    user_survey.save(update_fields=["use_score", "use_actions"])

    user_question = UserQuestion.objects.filter(
        user_survey=user_survey, origin_id=options[0].question_id
    ).first()
    snapshot_option = UserAnswerOption.objects.get(
        user_survey=user_survey, origin_id=options[0].id
    )
    snapshot_option.score = total
    snapshot_option.save(update_fields=["score"])

    answer = UserAnswer.objects.create(
        user=user,
        user_survey=user_survey,
        question=user_question,
        type=user_question.type,
    )
    answer.selected_options.add(snapshot_option)

    user_survey.submitted_at = now()
    evaluate_assessment(user_survey)
    user_survey.refresh_from_db()
    return user_survey


# ── CAP-1: a matched band delivers its materials ─────────────────────

def test_matched_band_delivers_its_materials(user, scored_survey, band, options):
    """A learner scoring inside the band gets the pinned catalog entries."""
    Material.objects.create(action=band, recommendable=_recommendable("101"))
    Material.objects.create(action=band, recommendable=_recommendable("102", "Advanced Stats"))

    user_survey = _enrol_and_score(user, scored_survey, options, 41)

    payload = _results(user, user_survey)
    assert payload["score"] == 41
    matched = [a for a in payload["actions"] if a["id"] == str(payload["actionId"])]
    assert matched, "the 36-45 band matched a score of 41"
    titles = sorted(m["data"]["title"] for m in matched[0]["materials"])
    assert titles == ["Advanced Stats", "Intro to Statistics"]


def test_a_band_with_no_materials_returns_an_empty_list(user, scored_survey, band, options):
    user_survey = _enrol_and_score(user, scored_survey, options, 41)

    payload = _results(user, user_survey)
    assert payload["actions"], "the band is still snapshotted"
    assert all(action["materials"] == [] for action in payload["actions"])


# ── CAP-2: a material is renderable on its own ───────────────────────

def test_a_material_carries_enough_to_render_and_route(user, scored_survey, band, options):
    """Source service, model, id and the cached payload — no call to courses."""
    recommendable = _recommendable("101")
    material = Material.objects.create(action=band, recommendable=recommendable)

    user_survey = _enrol_and_score(user, scored_survey, options, 41)

    card = _results(user, user_survey)["actions"][0]["materials"][0]
    assert card["sourceService"] == "courses"
    assert card["sourceModel"] == "Course"
    assert card["sourceId"] == "101"
    assert card["data"] == {"title": "Intro to Statistics", "slug": "course-101"}
    assert card["originId"] == material.id


# ── CAP-3: freeze versus live, both mutation-after-enrolment cases ───

def test_an_admin_repinning_the_band_does_not_reach_an_enrolled_learner(
    user, scored_survey, band, options
):
    """The *set* is frozen — the same rule every other User* row follows."""
    kept = Material.objects.create(action=band, recommendable=_recommendable("101"))

    user_survey = _enrol_and_score(user, scored_survey, options, 41)

    # Admin edits the band after enrolment: drops one, adds another.
    kept.delete()
    Material.objects.create(action=band, recommendable=_recommendable("999", "Something Else"))

    card_ids = [m["sourceId"] for m in _results(user, user_survey)["actions"][0]["materials"]]
    assert card_ids == ["101"], "the learner keeps what they were given at enrolment"


def test_a_source_service_updating_the_catalog_does_reach_an_enrolled_learner(
    user, scored_survey, band, options
):
    """The *payload* is live — a retitled course must not render stale."""
    recommendable = _recommendable("101")
    Material.objects.create(action=band, recommendable=recommendable)

    user_survey = _enrol_and_score(user, scored_survey, options, 41)

    # What the event consumer does on a `courses.course.updated` event.
    recommendable.data = {"title": "Statistics, Renamed", "slug": "course-101-renamed"}
    recommendable.save(update_fields=["data"])

    card = _results(user, user_survey)["actions"][0]["materials"][0]
    assert card["data"]["title"] == "Statistics, Renamed"
    assert card["data"]["slug"] == "course-101-renamed"


def test_deleting_the_catalog_row_leaves_the_card_standing(user, scored_survey, band, options):
    """SET_NULL plus the frozen copy: the learner keeps a renderable card."""
    recommendable = _recommendable("101")
    Material.objects.create(action=band, recommendable=recommendable)

    user_survey = _enrol_and_score(user, scored_survey, options, 41)
    recommendable.delete()

    snapshot = UserMaterial.objects.get(user_survey=user_survey)
    assert snapshot.recommendable_id is None

    card = _results(user, user_survey)["actions"][0]["materials"][0]
    assert card["sourceService"] == "courses"
    assert card["sourceId"] == "101"
    assert card["data"] == {"title": "Intro to Statistics", "slug": "course-101"}


# ── Snapshot wiring ──────────────────────────────────────────────────

def test_the_snapshot_writes_one_row_per_material(user, scored_survey, band, options):
    Material.objects.create(action=band, recommendable=_recommendable("101"))
    Material.objects.create(action=band, recommendable=_recommendable("102", "Advanced Stats"))

    user_survey, _ = enroll_user_in_assessment(user, scored_survey.id)

    user_action = UserAction.objects.get(user_survey=user_survey, origin_id=band.id)
    snapshots = UserMaterial.objects.filter(user_action=user_action)
    assert snapshots.count() == 2
    assert {s.user_survey_id for s in snapshots} == {user_survey.id}
    assert all(s.recommendable_id is not None for s in snapshots)


# ── Backfill ─────────────────────────────────────────────────────────

def _run_backfill():
    """Run 0023's `forwards` against the live app registry.

    These cover the backfill's *semantics* cheaply, with the fixtures the rest
    of this module uses: the historical models it asks for are identical to the
    current ones, so the real registry stands in for them.

    They are deliberately not the only coverage. `migrate` never runs here —
    pytest.ini passes `--no-migrations` — so no ordering, no atomic block and no
    historical registry is exercised by this path.
    `tests/test_user_materials_migration.py` applies 0022 and 0023 for real, in
    a child process, and is where a mismatch between the live and historical
    registries would surface.
    """
    import importlib

    from django.apps import apps as live_apps

    migration = importlib.import_module("user_surveys.migrations.0023_backfill_user_materials")
    migration.forwards(live_apps, None)


def test_backfill_fills_pre_migration_enrolments(user, scored_survey, band, options):
    """Rows snapshotted before 0022 get what a fresh enrolment would write."""
    Material.objects.create(action=band, recommendable=_recommendable("101"))
    user_survey, _ = enroll_user_in_assessment(user, scored_survey.id)

    # Stand in for an enrolment made before the table existed.
    UserMaterial.objects.all().delete()

    _run_backfill()

    snapshot = UserMaterial.objects.get(user_survey=user_survey)
    assert snapshot.source_id == "101"
    assert snapshot.data == {"title": "Intro to Statistics", "slug": "course-101"}
    assert snapshot.recommendable_id is not None


def test_backfill_skips_a_user_action_whose_action_is_gone(
    user, scored_survey, band, options
):
    """`Action` is hard-deleted, so origin_id dangles. Skip, do not fail."""
    Material.objects.create(action=band, recommendable=_recommendable("101"))
    user_survey, _ = enroll_user_in_assessment(user, scored_survey.id)
    UserMaterial.objects.all().delete()
    band.delete()

    _run_backfill()

    assert UserMaterial.objects.count() == 0
    assert UserAction.objects.filter(user_survey=user_survey).exists()


def test_backfill_does_not_double_write(user, scored_survey, band, options):
    """Re-running leaves rows the snapshot already wrote alone."""
    Material.objects.create(action=band, recommendable=_recommendable("101"))
    enroll_user_in_assessment(user, scored_survey.id)
    assert UserMaterial.objects.count() == 1

    _run_backfill()

    assert UserMaterial.objects.count() == 1


def test_a_rerun_cannot_hand_an_enrolled_learner_a_later_pinning(
    user, user2, scored_survey, band, options
):
    """The freeze rule survives a rollback-and-replay.

    Guarding on "which user_actions already have rows" let this through: a band
    with no materials at enrolment writes none, so it was absent from that set
    and a re-run backfilled it from whatever the admin had pinned since. The
    guard is now the whole table, so a re-run is a no-op.
    """
    user_survey, _ = enroll_user_in_assessment(user, scored_survey.id)
    assert UserMaterial.objects.count() == 0, "the band had nothing pinned"

    # A later enrolment writes rows, so the table is no longer empty — and an
    # admin pins to the band after our learner has already enrolled.
    Material.objects.create(action=band, recommendable=_recommendable("777", "Pinned Later"))
    enroll_user_in_assessment(user2, scored_survey.id)

    _run_backfill()

    assert not UserMaterial.objects.filter(user_survey=user_survey).exists()


def test_reversing_the_backfill_keeps_rows_the_snapshot_wrote(
    user, scored_survey, band, options
):
    """`backwards` is a no-op, because it cannot tell whose rows these are.

    `migrate user_surveys 0022` reverses this migration without dropping the
    table, so deleting here would permanently take every material a learner has
    been given since deploy.
    """
    import importlib

    from django.apps import apps as live_apps

    Material.objects.create(action=band, recommendable=_recommendable("101"))
    user_survey, _ = enroll_user_in_assessment(user, scored_survey.id)
    assert UserMaterial.objects.count() == 1

    migration = importlib.import_module("user_surveys.migrations.0023_backfill_user_materials")
    migration.backwards(live_apps, None)

    assert UserMaterial.objects.filter(user_survey=user_survey).count() == 1


# ── Band scope ───────────────────────────────────────────────────────

def test_an_unmatched_band_delivers_nothing(user, scored_survey, band, options):
    """A learner reads the advice for the band they landed in, and no other.

    Every band is still returned — a client shows the whole scale — but the
    recommendations belong to the matched one. Otherwise someone in the bottom
    band reads what the top band advises.
    """
    Material.objects.create(action=band, recommendable=_recommendable("101", "Matched"))
    other = Action.objects.create(survey=scored_survey, lower_limit=0, upper_limit=10)
    Material.objects.create(action=other, recommendable=_recommendable("202", "Unmatched"))

    user_survey = _enrol_and_score(user, scored_survey, options, 41)

    payload = _results(user, user_survey)
    delivered = {
        a["id"]: [m["data"]["title"] for m in a["materials"]] for a in payload["actions"]
    }
    assert len(delivered) == 2, "both bands are still returned"
    assert delivered.pop(str(payload["actionId"])) == ["Matched"]
    assert list(delivered.values()) == [[]], "the band they did not match stays silent"


def test_a_score_matching_no_band_delivers_nothing(user, scored_survey, band, options):
    """Bands are gapped and unvalidated (G6), so no match is a real state."""
    Material.objects.create(action=band, recommendable=_recommendable("101"))

    user_survey = _enrol_and_score(user, scored_survey, options, 12)

    assert user_survey.action_id is None, "12 falls outside the only band"
    payload = _results(user, user_survey)
    assert payload["actions"], "the band is still snapshotted"
    assert all(a["materials"] == [] for a in payload["actions"])

# ── Query cost ───────────────────────────────────────────────────────

def _material_queries(user, user_survey):
    """Count queries against the usermaterial table for one result page."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        payload = _results(user, user_survey)
    hits = [q for q in captured.captured_queries if "usermaterial" in q["sql"].lower()]
    return payload, len(hits)


def test_the_result_page_does_not_scale_queries_with_band_count(
    user, scored_survey, band, options
):
    """Materials are prefetched at the `actions` level, not per band.

    Resolving per band made the page cost one materials query per band, and a
    survey's band count is unbounded — as is the number of submissions the
    list query returns at once.
    """
    Material.objects.create(action=band, recommendable=_recommendable("0-0"))
    one_band = _enrol_and_score(user, scored_survey, options, 41)
    _, baseline = _material_queries(user, one_band)
    assert baseline == 1

    # Four more bands, three materials each, on a fresh enrolment.
    for i in range(1, 5):
        extra = Action.objects.create(
            survey=scored_survey, lower_limit=i * 100, upper_limit=i * 100 + 9
        )
        for j in range(3):
            Material.objects.create(action=extra, recommendable=_recommendable(f"{i}-{j}"))

    UserMaterial.objects.all().delete()
    one_band.delete()
    five_bands = _enrol_and_score(user, scored_survey, options, 41)

    payload, hits = _material_queries(user, five_bands)
    assert len(payload["actions"]) == 5, "all five bands are snapshotted"
    # Only the matched band delivers, so this is the one 36-45 material and
    # not the twelve pinned to the bands the learner did not land in.
    assert sum(len(a["materials"]) for a in payload["actions"]) == 1
    assert hits == baseline, "band count must not move the query count"


def _enrolment_material_inserts(user, survey):
    """Count INSERTs against the usermaterial table for one enrolment."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        user_survey, _ = enroll_user_in_assessment(user, survey.id)
    hits = [
        q
        for q in captured.captured_queries
        if "usermaterial" in q["sql"].lower() and q["sql"].lstrip().lower().startswith("insert")
    ]
    return user_survey, len(hits)


def test_enrolment_does_not_scale_inserts_with_material_count(
    user, scored_survey, band, options
):
    """The snapshot writes one INSERT per band, not one per material.

    A band's material count is admin-controlled and unbounded, and enrolment
    runs inside the snapshot transaction, so a row-at-a-time write puts the
    admin in charge of how long every learner's enrolment takes.
    """
    Material.objects.create(action=band, recommendable=_recommendable("0"))
    one_material, baseline = _enrolment_material_inserts(user, scored_survey)
    assert baseline == 1

    for i in range(1, 8):
        Material.objects.create(action=band, recommendable=_recommendable(str(i)))

    one_material.delete()
    many, hits = _enrolment_material_inserts(user, scored_survey)

    user_action = UserAction.objects.get(user_survey=many, origin_id=band.id)
    assert UserMaterial.objects.filter(user_action=user_action).count() == 8
    assert hits == baseline, "material count must not move the INSERT count"

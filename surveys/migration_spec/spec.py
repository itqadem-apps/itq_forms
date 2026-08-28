"""The mapping itself, one entry per legacy column."""

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class Disposition:
    """Base for what happens to one legacy column."""


@dataclass(frozen=True)
class Same(Disposition):
    """Copied to a target column of the same name."""

    transform: Optional[Callable] = None
    note: str = ""


@dataclass(frozen=True)
class Rename(Disposition):
    """Copied to a differently named target column."""

    to: str = ""
    transform: Optional[Callable] = None
    note: str = ""


@dataclass(frozen=True)
class Translate(Disposition):
    """Moved into the entity's translation table."""

    to: str = ""
    note: str = ""


@dataclass(frozen=True)
class Drop(Disposition):
    """Deliberately not carried. The reason is mandatory."""

    reason: str = ""

    def __post_init__(self):
        if not self.reason:
            raise ValueError("Drop() requires a reason -- an unexplained drop is the bug this module exists to prevent")


@dataclass(frozen=True)
class Const(Disposition):
    """Written as a fixed value, ignoring the legacy one."""

    value: object = None
    note: str = ""


@dataclass(frozen=True)
class Consumed(Disposition):
    """Read by the loader but not written to a column of its own."""

    by: str = ""


Column = Disposition


@dataclass
class Table:
    source: str
    target: Optional[str]
    columns: dict = field(default_factory=dict)
    note: str = ""


# --- value transforms -------------------------------------------------------

SURVEY_TYPE_MAP = {
    "survey": "survey",
    "questionnaire": "assessment",
    "curriculum": "curriculum",
    "exam": "exam",
    "smart_form": "form",
}

# 'list' and 'normal_form' were never implemented in legacy -- the solve
# template's branches for them are commented out. Only one row uses 'list':
# survey 146, an empty soft-deleted stub with no sections or questions, where
# the display option carries no meaning. Ruled to by_question. 'normal_form'
# has never been used and still raises.
DISPLAY_OPTION_MAP = {
    "single_question": "by_question",
    "list": "by_question",
}

# Legacy only ever writes 'next' (211 rows) and 'submit' (2). There is no
# 'jump' anywhere and submit_action_target_id is null on all 213 rows, so the
# target's jump branch has no legacy data behind it. 'submit' marks a terminal
# section; with nothing after it, 'next' is behaviourally identical.
SUBMIT_ACTION_MAP = {"next": "next", "jump": "jump", "submit": "next"}


def map_submit_action(v):
    if v in (None, ""):
        return v
    if v not in SUBMIT_ACTION_MAP:
        raise ValueError(f"unmapped submit_action {v!r}")
    return SUBMIT_ACTION_MAP[v]

# blogs_blog carried the lifecycle of a *course*, so it has two states the
# collection model never had. Neither is in SurveyCollection.STATUS_CHOICES, and
# `choices` is not a database constraint, so copying them straight through wrote
# three rows the model itself rejects -- full_clean() and every ModelForm refuse
# them. Mapped to the nearest state that exists:
#   started (1 row)  -> published : a running course is visible and open
#   ended   (2 rows) -> archived  : a finished one is visible but closed
COLLECTION_STATUS_MAP = {
    "draft": "draft",
    "pending": "pending",
    "published": "published",
    "archived": "archived",
    "suspended": "suspended",
    "started": "published",
    "ended": "archived",
}


def map_collection_status(v):
    if v in (None, ""):
        return v
    if v not in COLLECTION_STATUS_MAP:
        raise ValueError(f"unmapped blogs_blog.status {v!r}")
    return COLLECTION_STATUS_MAP[v]


# Legacy sponsor ids are the reverse of the frontend composable's.
# legacy 1 = National Bank of Egypt, 2 = Drosos Foundation;
# useSponsors.ts has 1 = Drosos, 2 = NBE. 3 = Advance Society, no frontend entry.
SPONSOR_MAP = {1: 2, 2: 1, 3: 3}


def map_survey_type(v):
    if v not in SURVEY_TYPE_MAP:
        raise ValueError(f"unmapped assessment_type {v!r}")
    return SURVEY_TYPE_MAP[v]


def map_display_option(v):
    if v not in DISPLAY_OPTION_MAP:
        raise ValueError(
            f"display_option {v!r} was never implemented in legacy and has no agreed "
            f"meaning in the new system -- decide what it means before loading this row"
        )
    return DISPLAY_OPTION_MAP[v]


def map_sponsor(v):
    if v is None:
        return None
    if v not in SPONSOR_MAP:
        raise ValueError(f"unknown sponsor id {v!r}")
    return SPONSOR_MAP[v]


# --- the mapping ------------------------------------------------------------

TABLES = [
    Table(
        source="assessments_assessment",
        target="surveys_survey",
        columns={
            "id": Same(note="reconciliation key; may be remapped on collision"),
            "created_at": Same(),
            "updated_at": Same(note="auto_now on the target -- restored by a post-write UPDATE"),
            "deleted_at": Same(note="column added in surveys/0037"),
            "title": Translate(to="title"),
            "description": Translate(to="description"),
            "short_description": Translate(to="short_description"),
            "language": Translate(to="language", note="also the language of every descendant"),
            "status": Same(),
            "assessment_type": Rename(to="survey_type", transform=map_survey_type),
            "display_option": Same(transform=map_display_option),
            "assignable_to_user": Const(value=True, note="ruled: is_for_child is true for every row"),
            "is_timed": Same(),
            "is_evaluable": Same(),
            "evaluation_type": Same(),
            "use_score": Same(),
            "use_classifications": Same(),
            "use_recommendations": Same(),
            "use_actions": Same(),
            "allow_end_based_on_answer_repeat": Same(),
            "end_based_on_answer_repeat_in_row": Same(),
            "answers_count_to_end": Same(),
            "create_option_for_each_classification": Same(),
            "allow_update_answer_options_scores_based_on_classification": Same(),
            "allow_update_answer_options_text_based_on_classification": Same(),
            "category_id": Same(note="int -> UUID via the category map"),
            "sponsor_id": Rename(to="sponsor", transform=map_sponsor),
            "price": Drop(reason="every legacy value is 0.0; the pricing app stays empty"),
            "content_type_id": Consumed(by="survey_collections M2M"),
            "object_id": Consumed(by="survey_collections M2M"),
        },
    ),
    Table(
        source="assessments_section",
        target="surveys_section",
        columns={
            "id": Same(),
            "assessment_id": Rename(to="survey_id"),
            "title": Translate(to="title"),
            "description": Translate(to="description"),
            "order": Same(),
            "is_hidden": Same(),
            "submit_action": Same(transform=map_submit_action),
            "submit_action_target_id": Same(note="self-FK, second pass -- null on every legacy row today"),
            "cover": Drop(reason="media deferred -- cover_asset_id loads NULL, not a legacy path"),
            "created_at": Same(),
            "updated_at": Same(),
            "deleted_at": Same(),
        },
    ),
    Table(
        source="assessments_question",
        target="surveys_question",
        columns={
            "id": Same(),
            "assessment_id": Rename(to="survey_id"),
            "section_id": Same(),
            "title": Translate(to="title"),
            "description": Translate(to="description"),
            "answer_time": Same(),
            "order": Same(),
            "is_required": Same(),
            "type": Same(),
            "cover": Drop(reason="media deferred"),
            "created_at": Same(),
            "updated_at": Same(),
            "deleted_at": Same(),
        },
    ),
    Table(
        source="assessments_answerschema",
        target="surveys_answerschema",
        columns={
            "id": Same(),
            "assessment_id": Rename(to="survey_id"),
            "section_id": Same(),
            "question_id": Same(note="OneToOne on the target; uniqueness asserted in preflight"),
            "type": Same(),
            "with_file": Same(),
            "is_mcq": Same(),
            "is_grid": Same(),
        },
    ),
    Table(
        source="assessments_answerschemaoption",
        target="surveys_answerschemaoption",
        columns={
            "id": Same(),
            "assessment_id": Rename(to="survey_id"),
            "section_id": Same(),
            "question_id": Same(),
            "schema_id": Same(),
            "classification_id": Same(),
            "text": Translate(to="text"),
            "score": Same(),
            "order": Same(note="nullable in legacy, NOT NULL here -- coalesced to schema position"),
            "is_row": Same(),
            "is_column": Same(),
            "ending_option": Same(),
            "image": Drop(reason="media deferred"),
        },
    ),
    Table(
        source="assessments_classification",
        target="classifications_classification",
        columns={
            "id": Same(),
            "assessment_id": Rename(to="survey_id"),
            "name": Translate(to="name"),
            "score": Same(),
            "created_at": Same(),
            "updated_at": Same(),
            "deleted_at": Same(),
        },
    ),
    Table(
        source="assessments_action",
        target="recommendations_action",
        columns={
            "id": Same(),
            "assessment_id": Rename(to="survey_id"),
            "title": Translate(to="title"),
            "description": Translate(to="description"),
            "upper_limit": Same(),
            "lower_limit": Same(),
        },
    ),
    Table(
        source="assessments_recommendation",
        target="recommendations_recommendation",
        columns={
            "id": Same(),
            "assessment_id": Rename(to="survey_id"),
            "option_id": Same(),
            "description": Translate(to="description"),
            "created_at": Same(),
            "updated_at": Same(),
            "deleted_at": Same(),
        },
    ),
    Table(
        source="classifications_category",
        target="taxonomy_category",
        columns={
            "id": Rename(to="category_id", note="int -> deterministic UUID"),
            "name": Translate(to="name", note="one row per language key in the jsonb"),
            "slug": Translate(to="slug"),
            "tree_id": Same(note="int -> stable UUID"),
            "parent_id": Consumed(by="path_text"),
            "lft": Consumed(by="path_text"),
            "rght": Consumed(by="path_text"),
            "level": Consumed(by="path_text"),
            "created_at": Drop(reason="taxonomy_category has no created_at"),
            "updated_at": Drop(reason="taxonomy_category has no updated_at"),
        },
    ),
    Table(
        source="blogs_blog",
        target="survey_collections_surveycollection",
        columns={
            "id": Same(note="must survive -- survey object_id resolves against it"),
            "status": Same(transform=map_collection_status),
            "type": Same(),
            "category_id": Same(),
            "sponsor_id": Rename(to="sponsor", transform=map_sponsor),
            "title": Translate(to="title"),
            "description": Translate(to="description"),
            "short_description": Translate(to="short_description"),
            "slug": Translate(to="slug"),
            "language": Translate(to="language"),
            "created_at": Same(),
            "updated_at": Same(),
            "deleted_at": Same(),
            "price": Drop(reason="all zeros"),
            "privacy_status": Drop(reason="removed from the model in survey_collections/0003"),
            "author_id": Drop(reason="removed from the model in survey_collections/0003"),
            "video_list_id": Drop(reason="removed from the model in survey_collections/0003"),
            "course_id": Drop(reason="the model has no course field"),
        },
    ),
    Table(
        source="assessments_recommendedmaterial",
        target=None,
        note="deferred in full -- recommendable_id needs the NATS projections",
        columns={
            "id": Drop(reason="table deferred"),
            "action_id": Drop(reason="table deferred"),
            "content_type_id": Drop(reason="table deferred"),
            "object_id": Drop(reason="table deferred"),
        },
    ),
    Table(
        source="classifications_tag",
        target=None,
        note="no tagging concept in the new system",
        columns={c: Drop(reason="no tagging concept in the new system")
                 for c in ("id", "name", "slug", "created_at", "updated_at")},
    ),
    Table(
        source="classifications_modeltag",
        target=None,
        note="dropped with classifications_tag",
        columns={c: Drop(reason="dropped with classifications_tag")
                 for c in ("id", "tag_id", "content_type_id", "object_id")},
    ),
]


# --- the target side --------------------------------------------------------
#
# assert_total() below walks the LEGACY catalog, so it can only catch a legacy
# column nobody ruled on. It is structurally blind to a *target* column that has
# no legacy source -- which is how surveys_survey.organization_id was missed:
# it is nullable, so it tripped no NOT NULL check, and it appears in no legacy
# table, so the mapping never had to mention it. Every row the loader inserted
# got NULL, and organization_id is the key that gates all NATS publishing, so
# those rows could never be published.
#
# So the target catalog gets its own totality check. Every column of every table
# the loader writes must be either supplied by the loader or listed here with a
# reason. A new target column added by a future migration fails the load until
# someone rules on it.

TARGET_UNWRITTEN = {
    ("surveys_survey", "cover_id"): "media deferred",
    ("surveys_survey", "thumb_id"): "media deferred",
    ("surveys_survey", "time_limit"):
        "legacy has is_timed but no duration column, so there is nothing to carry. "
        "The one timed legacy survey therefore enforces no limit until someone sets one.",
    ("surveys_section", "cover_asset_id"): "media deferred",
    ("surveys_question", "cover_asset_id"): "media deferred",
    ("surveys_answerschemaoption", "image_asset_id"): "media deferred",
}


def assert_target_total(target_columns: dict, written: dict) -> None:
    """Refuse to run unless every column of every written target table is ruled on.

    `target_columns` maps table -> set of column names, read from the target's
    information_schema. `written` maps table -> set of columns the loader
    supplies (whether from legacy, a constant, or a second pass).
    """
    problems = []
    for table, supplied in sorted(written.items()):
        actual = target_columns.get(table)
        if actual is None:
            problems.append(f"{table}: the loader writes it but the target has no such table")
            continue
        for missing in sorted(actual - set(supplied)):
            if (table, missing) in TARGET_UNWRITTEN:
                continue
            problems.append(
                f"{table}.{missing}: exists on the target, the loader never writes it, and "
                f"no ruling covers it -- decide what it should hold and either write it or "
                f"add it to TARGET_UNWRITTEN with a reason"
            )
        for gone in sorted(set(supplied) - actual):
            problems.append(f"{table}.{gone}: the loader writes it but the target has no such column")
    stale = [f"{t}.{c}" for (t, c) in TARGET_UNWRITTEN
             if c not in target_columns.get(t, set())]
    for s in sorted(stale):
        problems.append(f"{s}: ruled unwritten but no longer exists on the target")
    if problems:
        raise SystemExit(
            "the target side of the mapping is not total:\n  " + "\n  ".join(problems)
        )


def assert_total(legacy_columns: dict) -> None:
    """Refuse to run unless the mapping covers the live legacy catalog exactly.

    `legacy_columns` maps table name -> set of column names, read from
    information_schema on the source database.
    """
    problems = []
    for table in TABLES:
        actual = legacy_columns.get(table.source)
        if actual is None:
            problems.append(f"{table.source}: mapped but not present in the source database")
            continue
        mapped = set(table.columns)
        for missing in sorted(actual - mapped):
            problems.append(
                f"{table.source}.{missing}: present in the database, absent from the mapping -- "
                f"rule on it before loading"
            )
        for extra in sorted(mapped - actual):
            problems.append(f"{table.source}.{extra}: mapped but no longer exists in the source")
    if problems:
        raise SystemExit(
            "the legacy->itq_forms mapping is not total:\n  " + "\n  ".join(problems)
        )

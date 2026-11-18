"""The recommendables list holds only the caller's organization's courses and narrows by search
(intake report #134, story action-recommendables 1.1)."""

import uuid

import pytest

from conftest import ORG
from pkg_auth.authorization import AuthContext, OrgId, UserId
from recommendations.models import Recommendable
from recommendations.schemas.queries import recommendables as module
from tests.test_action_materials import _Context

pytestmark = pytest.mark.django_db

OTHER = uuid.UUID("22222222-2222-2222-2222-222222222222")
PLATFORM = uuid.UUID("99999999-9999-9999-9999-999999999999")

LIST = """
query ($search: String, $language: String) {
  recommendables(search: $search, language: $language) { id sourceId title(language: $language) }
}
"""


class _OrgContext(_Context):
    def __init__(self, user, org):
        super().__init__(user)
        if org is not None:
            self.auth_context = AuthContext(
                user_id=UserId(user.id),
                organization_id=OrgId(org),
                role_names=frozenset({"org-admin"}),
                perms=frozenset(),
            )


@pytest.fixture(autouse=True)
def platform(monkeypatch):
    monkeypatch.setattr(
        module,
        "is_platform_context",
        lambda auth_ctx: auth_ctx.organization_id.value == PLATFORM,
    )


def _list(user, org=ORG, search=None, language=None):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        LIST,
        variable_values={"search": search, "language": language},
        context_value=_OrgContext(user, org),
    )
    assert result.errors is None, result.errors
    return result.data["recommendables"]


def _ids(rows):
    return [row["sourceId"] for row in rows]


def _course(source_id, org=ORG, *, title=None, translations=None, nested=True,
            subject="courses.course.updated", service="courses", model="Course"):
    entity = {}
    if title is not None:
        entity["title"] = title
    if translations is not None:
        entity["translations"] = translations
    if nested:
        if org is not None:
            entity["organization_id"] = str(org)
        data = {"aggregate_id": source_id, "course": entity}
    else:
        data = {"aggregate_id": source_id, **entity}
        if org is not None:
            data["organization_id"] = str(org)
    data["subject"] = subject
    return Recommendable.objects.create(
        source_service=service, source_model=model, source_id=source_id, data=data
    )


def test_only_own_org_courses(user):
    _course("a1", title="Alpha")
    _course("b1", OTHER, title="Beta")
    assert _ids(_list(user)) == ["a1"]
    assert _ids(_list(user, OTHER)) == ["b1"]


def test_org_in_envelope(user):
    _course("env", title="Envelope", nested=False)
    _course("env-other", OTHER, title="Envelope other", nested=False)
    assert _ids(_list(user)) == ["env"]


def test_no_org_shown_to_nobody(user):
    _course("orphan", None, title="Orphan")
    assert _list(user) == []
    assert _list(user, PLATFORM) == []


def test_anonymous_gets_empty(user):
    _course("a1", title="Alpha")
    assert _list(user, org=None) == []


def test_platform_sees_every_org(user):
    _course("a1", title="Alpha")
    _course("b1", OTHER, title="Beta")
    assert _ids(_list(user, PLATFORM)) == ["a1", "b1"]


def test_other_kinds_left_out(user):
    _course("v1", title="Video", service="videos", model="Video")
    _course("ar1", title="Article", service="articles", model="Article")
    _course("c1", title="Course")
    assert _ids(_list(user)) == ["c1"]


def test_deleted_left_out(user):
    _course("gone", title="Gone", subject="courses.course.deleted")
    _course("kept", title="Kept")
    assert _ids(_list(user)) == ["kept"]


def test_search_matches_any_language(user):
    _course("c1", translations=[
        {"language": "ar", "title": "مقدمة"},
        {"language": "en", "title": "Intro"},
    ])
    _course("c2", title="Unrelated")
    assert _ids(_list(user, search="intro")) == ["c1"]
    assert _ids(_list(user, search="  INTRO ")) == ["c1"]
    assert _ids(_list(user, search="مقد")) == ["c1"]


def test_blank_search_matches_everything(user):
    _course("c1", title="One")
    _course("c2", title="Two")
    assert _ids(_list(user, search="  ")) == _ids(_list(user)) == ["c1", "c2"]


def test_title_language(user):
    _course("c1", translations=[
        {"language": "en", "title": "Intro"},
        {"language": "ar", "title": "مقدمة"},
    ])
    _course("c2", translations=[{"language": "en", "title": "Only English"}])
    rows = {row["sourceId"]: row["title"] for row in _list(user, language="ar")}
    assert rows == {"c1": "مقدمة", "c2": "Only English"}
    rows = {row["sourceId"]: row["title"] for row in _list(user)}
    assert rows == {"c1": "Intro", "c2": "Only English"}


def test_flat_title_fallback(user):
    _course("flat", title="Flat Course")
    _course("none")
    rows = _list(user, language="ar")
    assert [(row["sourceId"], row["title"]) for row in rows] == [("flat", "Flat Course"), ("none", None)]
    assert _ids(_list(user, search="flat co")) == ["flat"]


def test_limit_twenty_by_title(user):
    for n in range(25):
        _course(f"c{n:02d}", title=f"Course {24 - n:02d}")
    rows = _list(user, search="course")
    assert len(rows) == 20
    assert [row["title"] for row in rows] == [f"Course {n:02d}" for n in range(20)]


def test_order_case_insensitive_ties_by_creation_order(user):
    _course("z", title="beta")
    _course("y", title="Alpha")
    _course("x", title="alpha")
    assert _ids(_list(user)) == ["y", "x", "z"]


def test_order_follows_requested_language(user):
    _course("c1", translations=[{"language": "en", "title": "Alpha"}, {"language": "ar", "title": "ب"}])
    _course("c2", translations=[{"language": "en", "title": "Beta"}, {"language": "ar", "title": "أ"}])
    assert _ids(_list(user)) == ["c1", "c2"]
    assert _ids(_list(user, language="en")) == ["c1", "c2"]
    assert _ids(_list(user, language="ar")) == ["c2", "c1"]


def test_row_without_subject_still_returned(user):
    row = _course("nosub", title="No subject")
    data = dict(row.data)
    del data["subject"]
    row.data = data
    row.save(update_fields=["data"])
    assert _ids(_list(user)) == ["nosub"]


def test_whitespace_translation_title_falls_through(user):
    _course("c1", translations=[{"language": "ar", "title": "   "}, {"language": "en", "title": "Intro"}])
    assert _list(user, language="ar")[0]["title"] == "Intro"


def test_non_string_flat_title_is_null_and_unmatched(user):
    _course("c1", title={"en": "Dict title"})
    rows = _list(user)
    assert [(row["sourceId"], row["title"]) for row in rows] == [("c1", None)]
    assert _list(user, search="dict") == []


def test_language_match_ignores_case(user):
    _course("c1", translations=[{"language": "en", "title": "Intro"}, {"language": "ar", "title": "مقدمة"}])
    assert _list(user, language="AR")[0]["title"] == "مقدمة"


def test_existing_fields_unchanged(user):
    _course("c1", title="Alpha")
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        "{ recommendables { id sourceService sourceModel sourceId data createdAt updatedAt } }",
        context_value=_OrgContext(user, ORG),
    )
    assert result.errors is None, result.errors
    row = result.data["recommendables"][0]
    assert row["sourceService"] == "courses" and row["sourceModel"] == "Course"

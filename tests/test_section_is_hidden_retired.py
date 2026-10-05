"""Story survey-flow 1.4 — `Section.is_hidden` is retired (`forms:AD-9`).

The flag is no longer authorable: `createSection` and `updateSection` ignore it rather than refuse
it, because the admin's duplicate-section flow still sends the source section's value. Nothing
reads it to hide or exclude a question. The column and the existing rows are untouched — moving a
hidden section's questions out is story 1.5, after the 1.6 backfill (`forms:AD-14`).
"""

from surveys.inputs import SectionInput
from surveys.models import Section
from surveys.schemas.mutations.sections import SectionMutations


def _resolver(name):
    fn = getattr(SectionMutations, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def test_create_section_ignores_is_hidden(survey):
    created = _resolver("create_section")(
        SectionMutations(), None, survey_id=str(survey.id), input=SectionInput(title="S", is_hidden=True), django_user=None
    )
    assert Section.objects.get(pk=created.pk).is_hidden is False


def test_update_section_ignores_is_hidden_and_moves_no_data(survey, section):
    Section.objects.filter(pk=section.pk).update(is_hidden=True)

    _resolver("update_section")(
        SectionMutations(), None, id=str(section.id), input=SectionInput(title="Renamed", is_hidden=False), django_user=None
    )

    section.refresh_from_db()
    assert section.title == "Renamed"
    assert section.is_hidden is True, "an existing row keeps its value until story 1.5"
    assert section.questions.exists()


def test_is_hidden_is_deprecated_on_every_schema_surface():
    from surveys import schema as schema_module

    sdl = schema_module.schema.as_str()
    for type_name in ("input SectionInput", "type SectionType", "type UserSectionType"):
        block = sdl[sdl.index(type_name + " {"):]
        block = block[: block.index("}")]
        line = next(ln for ln in block.splitlines() if ln.strip().startswith("isHidden"))
        assert "@deprecated" in line, type_name

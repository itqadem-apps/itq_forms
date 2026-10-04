"""`reconcile_categories --map`: pair a legacy category with its tree counterpart
when the two name the same topic in different wording.

Production, 2026-09-30: four legacy rows (e.g. 'التعليم الدمجي') had tree
counterparts worded differently ('التعليم الشامل'), so slug/name matching left
them unmatched. Every pair is validated before anything is written.
"""
from __future__ import annotations

import uuid
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from surveys.models import Survey
from taxonomy.models import Category, CategoryTranslation

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

TREE = uuid.UUID("11111111-1111-1111-1111-111111111111")
LEGACY_TREE = uuid.UUID("99999999-9999-9999-9999-999999999999")


def _category(tree_id, name, slug):
    category = Category.objects.create(tree_id=tree_id, name=name)
    CategoryTranslation.objects.create(category=category, language="ar", name=name, slug=slug)
    return category


@pytest.fixture
def rows(db):
    same = _category(TREE, "التوحد", "autism")
    reworded = _category(TREE, "التعليم الشامل", "inclusive-education")
    legacy_same = _category(LEGACY_TREE, "التوحد", "التوحد")
    legacy_reworded = _category(LEGACY_TREE, "التعليم الدمجي", "التعليم-الدمجي")
    survey = Survey.objects.create(organization_id=ORG, survey_type="survey", category=legacy_reworded)
    return locals()


def _run(*args):
    out = StringIO()
    call_command("reconcile_categories", "--tree-id", str(TREE), *args, stdout=out)
    return out.getvalue()


def test_without_a_map_the_reworded_row_is_unmatched(rows):
    out = _run("--dry-run")

    assert "Dry run: 1 matched, 0 ambiguous, 1 unmatched." in out


def test_a_map_pairs_the_reworded_row_and_keeps_the_summary_format(rows):
    pair = f"{rows['legacy_reworded'].category_id}={rows['reworded'].category_id}"

    out = _run("--dry-run", "--map", pair)

    assert "Dry run: 2 matched, 0 ambiguous, 0 unmatched." in out
    assert f"  map  'التعليم الدمجي'  {rows['legacy_reworded'].category_id}" in out
    assert Category.objects.filter(category_id=rows["legacy_reworded"].category_id).exists()


def test_a_mapped_run_repoints_the_surveys_and_retires_the_legacy_row(rows):
    pair = f"{rows['legacy_reworded'].category_id}={rows['reworded'].category_id}"

    _run("--map", pair)

    rows["survey"].refresh_from_db()
    assert rows["survey"].category_id == rows["reworded"].category_id
    assert not Category.objects.filter(tree_id=LEGACY_TREE).exists()


@pytest.mark.parametrize(
    "make_pair, message",
    [
        (lambda r: "not-a-pair", "expected LEGACY_ID=TARGET_ID"),
        (lambda r: f"{r['legacy_reworded'].category_id}=nope", "expected LEGACY_ID=TARGET_ID"),
        (lambda r: f"{r['reworded'].category_id}={r['same'].category_id}", "not a live legacy category"),
        (lambda r: f"{r['legacy_reworded'].category_id}={uuid.uuid4()}", "not a live category of the tree"),
    ],
)
def test_a_bad_pair_stops_before_any_write(rows, make_pair, message):
    with pytest.raises(CommandError, match=message):
        _run("--map", make_pair(rows))

    assert Category.objects.filter(tree_id=LEGACY_TREE).count() == 2


def test_a_legacy_row_mapped_twice_is_refused(rows):
    legacy = rows["legacy_reworded"].category_id
    with pytest.raises(CommandError, match="mapped twice"):
        _run(
            "--map", f"{legacy}={rows['reworded'].category_id}",
            "--map", f"{legacy}={rows['same'].category_id}",
        )

    assert Category.objects.filter(tree_id=LEGACY_TREE).count() == 2

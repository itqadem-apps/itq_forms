"""The primary language must never snapshot as blank text.

A question whose primary-language translation row exists but carries a null
title used to snapshot with no text at all: `_build_translations` merged the
source model's own value with `setdefault`, which is a no-op once the key is
present, even when the value behind it is `None`. Questions with no translation
row got the fallback and rendered fine, so the failure looked like one damaged
record rather than a rule.
"""

from types import SimpleNamespace

from user_surveys.services import _build_translations


def _row(language, **fields):
    return SimpleNamespace(language=language, **fields)


def test_a_null_primary_translation_falls_back_to_the_source():
    result = _build_translations(
        [_row("ar", title=None)],
        ["title"],
        source=SimpleNamespace(title="هل يتجنب النظر في العينين؟"),
        primary_lang="ar",
    )
    assert result["ar"]["title"] == "هل يتجنب النظر في العينين؟"


def test_an_empty_primary_translation_falls_back_to_the_source():
    result = _build_translations(
        [_row("ar", title="")],
        ["title"],
        source=SimpleNamespace(title="نص السؤال"),
        primary_lang="ar",
    )
    assert result["ar"]["title"] == "نص السؤال"


def test_a_real_primary_translation_still_wins():
    result = _build_translations(
        [_row("ar", title="مترجم")],
        ["title"],
        source=SimpleNamespace(title="نص السؤال"),
        primary_lang="ar",
    )
    assert result["ar"]["title"] == "مترجم"


def test_a_missing_primary_row_still_falls_back():
    result = _build_translations(
        [_row("en", title="Question text")],
        ["title"],
        source=SimpleNamespace(title="نص السؤال"),
        primary_lang="ar",
    )
    assert result["ar"]["title"] == "نص السؤال"
    assert result["en"]["title"] == "Question text"


def test_other_languages_are_left_alone_when_null():
    """The fallback is a primary-language rule. A null English title means the
    question is untranslated into English, and inventing Arabic text for it
    would be worse than leaving the gap visible."""
    result = _build_translations(
        [_row("en", title=None)],
        ["title"],
        source=SimpleNamespace(title="نص السؤال"),
        primary_lang="ar",
    )
    assert result["en"]["title"] is None

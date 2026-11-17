"""Find the empty recommendations the old "Add recommendation" button left behind (intake report
#133, stories add-recommendation 2.1 and 2.2).

Before lyr-surveys 165e523 every press of the button saved a recommendation with no text, and each
unused press still shows as a blank box on the Build page. A recommendation is **empty** when it is
live (`deleted_at` null) and no translation carries text: it has no `RecommendationTranslation`
row, or every row's `description` is null or blank once HTML tags, `&nbsp;` and whitespace are
removed. Text in any language, "default" included, makes it not empty.

A recommendation belongs to its `survey_id`, else to its option's `survey_id`; with neither it is
counted under no survey (`None`).

Reads only. The report ships as migration 0006 (writes nothing); the soft-delete apply (story 2.2)
reuses `find_empty` and ships in its own release. Learner copies (`UserRecommendation`) are
counted (live ones only), never read beyond their `origin_id` and never written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TAG = re.compile(r"<[^>]*>")
# &nbsp; (also without its semicolon), the other HTML spaces, and zero-width characters: an editor
# leaves these behind and none of them shows as text.
_INVISIBLE = re.compile(
    r"&(?:nbsp|ensp|emsp|thinsp|zwnj|zwj);?|&#(?:160|8194|8195|8201|8203|8204|8205|8288|65279);"
    r"|&#x(?:a0|2002|2003|2009|200b|200c|200d|2060|feff);|[\u200b-\u200d\u2060\ufeff]",
    re.IGNORECASE,
)
# Tags that show something with no text around them.
_MEDIA = re.compile(r"<\s*(?:img|iframe|video|audio|embed|object|svg)\b", re.IGNORECASE)


def is_blank(text: str | None) -> bool:
    """True when `text` is null, or empty once HTML tags, `&nbsp;` and whitespace are removed."""
    if text is None:
        return True
    return not _INVISIBLE.sub(" ", _TAG.sub("", text)).strip()


def has_media(text: str | None) -> bool:
    """True when a blank `text` still holds an image, video or embed tag."""
    return bool(text) and bool(_MEDIA.search(text))


@dataclass
class Found:
    # survey id (None: no survey) -> ids of its empty recommendations, ascending
    by_survey: dict[int | None, list[int]] = field(default_factory=dict)
    no_translation: list[int] = field(default_factory=list)
    only_blank: list[int] = field(default_factory=list)
    # empty ids whose blank text still holds an image, video or embed: blank by the rule, but they
    # may show something on the Build page, so story 2.2 must rule on them before deleting
    with_media: list[int] = field(default_factory=list)
    learner_copies: int = 0

    @property
    def ids(self) -> list[int]:
        return sorted(self.no_translation + self.only_blank)


CHUNK = 1000


def find_empty() -> Found:
    """Every live recommendation with no text in any language, read and never written."""
    from recommendations.models import Recommendation, RecommendationTranslation
    from user_surveys.models import UserRecommendation

    live = Recommendation._base_manager.filter(deleted_at__isnull=True)
    rows = live.order_by("id").values_list("id", "survey_id", "option__survey_id")
    owners = {pk: own if own is not None else via_option for pk, own, via_option in rows}

    has_row: set[int] = set()
    has_text: set[int] = set()
    has_media_tag: set[int] = set()
    translations = RecommendationTranslation._base_manager.filter(recommendation_id__in=live.values("id"))
    for rec_id, description in translations.values_list("recommendation_id", "description"):
        has_row.add(rec_id)
        if not is_blank(description):
            has_text.add(rec_id)
        elif has_media(description):
            has_media_tag.add(rec_id)

    found = Found()
    for pk, survey_id in owners.items():
        if pk in has_text:
            continue
        (found.only_blank if pk in has_row else found.no_translation).append(pk)
        found.by_survey.setdefault(survey_id, []).append(pk)
        if pk in has_media_tag:
            found.with_media.append(pk)

    ids = found.ids
    copies = UserRecommendation._base_manager.filter(deleted_at__isnull=True)
    found.learner_copies = sum(
        copies.filter(origin_id__in=ids[i : i + CHUNK]).count() for i in range(0, len(ids), CHUNK)
    )
    return found


def summary(found: Found) -> list[str]:
    """The report as log lines: totals, the split, one line per survey, the no-survey count and
    the learner copies pointing at an empty recommendation."""
    lines = [
        f"total: {len(found.ids)} empty recommendation(s)",
        f"no translation: {len(found.no_translation)}",
        f"only blank translations: {len(found.only_blank)}",
        f"blank but holding an image, video or embed: {len(found.with_media)}",
    ]
    for survey_id in sorted(k for k in found.by_survey if k is not None):
        lines.append(f"survey {survey_id}: {len(found.by_survey[survey_id])}")
    lines.append(f"no survey: {len(found.by_survey.get(None, []))}")
    lines.append(f"learner copies pointing at an empty recommendation: {found.learner_copies}")
    return lines

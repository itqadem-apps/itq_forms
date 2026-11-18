"""Readers over a recommendable's stored course payload (intake report #134).

The catalog keeps the whole latest event payload in ``Recommendable.data``.
Courses publish the entity under a nested ``course`` dict, with the envelope
as the fallback, the same shape ``external_references/courses.py`` reads.
"""

from __future__ import annotations

from typing import Any, Optional

COURSE_SERVICE = "courses"
COURSE_MODEL = "Course"
COURSE_DELETED = "courses.course.deleted"


def entity(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    nested = data.get("course")
    return nested if isinstance(nested, dict) else data


def organization_id(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    raw = entity(data).get("organization_id") or data.get("organization_id")
    text = str(raw).strip() if raw else ""
    return text or None


def _translations(data: Any) -> list[dict[str, Any]]:
    raw = entity(data).get("translations")
    if not isinstance(raw, list):
        return []
    return [tr for tr in raw if isinstance(tr, dict) and _text(tr.get("title"))]


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.strip() else None


def _flat_title(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    return _text(entity(data).get("title")) or _text(data.get("title"))


def titles(data: Any) -> list[str]:
    """Every title the course carries, in any language, for search."""
    found = [tr["title"] for tr in _translations(data)]
    flat = _flat_title(data)
    if flat:
        found.append(flat)
    return found


def shown_title(data: Any, language: Optional[str] = None) -> Optional[str]:
    """The requested language's title, else the first translation's, else the flat title."""
    translations = _translations(data)
    if language:
        wanted = language.casefold()
        for tr in translations:
            if str(tr.get("language") or "").casefold() == wanted:
                return tr["title"]
    if translations:
        return translations[0]["title"]
    return _flat_title(data)


def matches(data: Any, search: Optional[str]) -> bool:
    term = (search or "").strip().casefold()
    if not term:
        return True
    return any(term in title.casefold() for title in titles(data))

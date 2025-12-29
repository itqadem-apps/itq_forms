import random
import string

from django.conf import settings
from django.db import transaction

from .models import Status, Survey


def _pick_choice(choices, default=None):
    if not choices:
        return default
    return random.choice([c[0] for c in choices])


def _words(min_words=3, max_words=8):
    word_bank = [
        "employee",
        "experience",
        "engagement",
        "feedback",
        "culture",
        "process",
        "training",
        "performance",
        "quality",
        "service",
        "satisfaction",
        "workplace",
        "onboarding",
        "communication",
        "leadership",
        "support",
        "wellbeing",
        "teamwork",
        "growth",
        "goals",
    ]
    count = random.randint(min_words, max_words)
    return " ".join(random.choice(word_bank) for _ in range(count))


def _sentence(min_words=7, max_words=16):
    text = _words(min_words=min_words, max_words=max_words)
    return f"{text[:1].upper()}{text[1:]}."


def _short_token(length=6):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


class SurveyFactory:
    @classmethod
    def build(cls, **overrides):
        language = overrides.pop("language", None)
        if language is None:
            language = _pick_choice(getattr(settings, "LANGUAGES", None), default=settings.LANGUAGE_CODE)

        title = overrides.pop("title", None)
        if title is None:
            title = f"{_words(2, 5).title()} ({_short_token()})"

        short_description = overrides.pop("short_description", None)
        if short_description is None:
            short_description = _sentence(6, 10)[:300]

        description = overrides.pop("description", None)
        if description is None:
            description = "\n".join([_sentence(10, 18) for _ in range(random.randint(2, 4))])

        status = overrides.pop("status", None) or random.choice(
            [Status.STATUS_DRAFT, Status.STATUS_PENDING, Status.STATUS_PUBLISHED]
        )

        assessment_type = overrides.pop("assessment_type", None) or Survey.ASSESSMENT_TYPE_SURVEY
        display_option = overrides.pop("display_option", None) or _pick_choice(
            Survey.DISPLAY_OPTIONS, default=Survey.DISPLAY_OPTION_SINGLE_QUESTION
        )

        is_timed = overrides.pop("is_timed", None)
        if is_timed is None:
            is_timed = random.random() < 0.25

        assignable_to_user = overrides.pop("assignable_to_user", None)
        if assignable_to_user is None:
            assignable_to_user = random.random() < 0.35

        is_evaluable = overrides.pop("is_evaluable", None)
        if is_evaluable is None:
            is_evaluable = random.random() < 0.2

        evaluation_type = overrides.pop("evaluation_type", None)
        if evaluation_type is None:
            evaluation_type = (
                Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION
                if random.random() < 0.8
                else Survey.EVALUATION_TYPE_MANUAL_EVALUATION
            )

        return Survey(
            title=title,
            short_description=short_description,
            description=description,
            language=language,
            status=status,
            assessment_type=assessment_type,
            display_option=display_option,
            is_timed=is_timed,
            assignable_to_user=assignable_to_user,
            is_evaluable=is_evaluable,
            evaluation_type=evaluation_type,
            **overrides,
        )

    @classmethod
    def create(cls, **overrides):
        instance = cls.build(**overrides)
        instance.full_clean()
        instance.save()
        return instance

    @classmethod
    def create_batch(cls, size, **overrides):
        with transaction.atomic():
            return [cls.create(**overrides) for _ in range(size)]

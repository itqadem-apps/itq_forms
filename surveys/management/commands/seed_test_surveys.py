"""
Seed 10 test surveys covering all solve/evaluate workflows end-to-end.

Usage:
    python manage.py seed_test_surveys
    python manage.py seed_test_surveys --truncate   # delete existing test surveys first
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from surveys.models import (
    Action,
    ActionTranslation,
    AnswerSchema,
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
    Classification,
    ClassificationTranslation,
    Question,
    QuestionTranslation,
    Recommendation,
    RecommendationTranslation,
    Section,
    SectionTranslation,
    Status,
    Survey,
    SurveyTranslation,
)

def _classification(survey, name, score=None):
    """Create a Classification and its primary translation."""
    c = Classification.objects.create(survey=survey, score=score)
    ClassificationTranslation.objects.create(classification=c, language="en", name=name)
    return c


def _recommendation(survey, option, description):
    """Create a Recommendation and its primary translation."""
    r = Recommendation.objects.create(survey=survey, option=option)
    RecommendationTranslation.objects.create(recommendation=r, language="en", description=description)
    return r


def _action(survey, title, description=None, lower_limit=0, upper_limit=0):
    """Create an Action and its primary translation."""
    a = Action.objects.create(survey=survey, lower_limit=lower_limit, upper_limit=upper_limit)
    ActionTranslation.objects.create(action=a, language="en", title=title, description=description)
    return a


# Prefix to identify test surveys for easy cleanup
TAG = "[TEST] "


def _status(survey, status_str):
    s = Status.objects.create(survey=survey, status=status_str)
    survey.status = s
    survey.save(update_fields=["status"])
    return s


def _create_survey(title, description=None, **kwargs):
    """Create a Survey and its primary translation."""
    survey = Survey.objects.create(**kwargs)
    SurveyTranslation.objects.create(
        survey=survey,
        language="en",
        title=title,
        description=description,
    )
    return survey


def _section(survey, title, order, **kwargs):
    """Create a section. Note: post_save signal auto-creates a default question."""
    sec = Section.objects.create(survey=survey, title=title, order=order, **kwargs)
    # Delete the auto-created default question (from post_save signal)
    sec.questions.all().delete()
    return sec


def _question(section, title, qtype, order, is_required=False, **kwargs):
    """Create a question. post_save signal auto-creates AnswerSchema + default options."""
    q = Question.objects.create(
        survey=section.survey,
        section=section,
        title=title,
        type=qtype,
        order=order,
        is_required=is_required,
        **kwargs,
    )
    # Delete auto-created default options (we'll create our own)
    if hasattr(q, "answer_schema"):
        q.answer_schema.options.all().delete()
    return q


def _option(question, text, order, score=None, **kwargs):
    schema = question.answer_schema
    return AnswerSchemaOption.objects.create(
        survey=question.survey,
        section=question.section,
        question=question,
        schema=schema,
        text=text,
        score=score,
        order=order,
        **kwargs,
    )


def _opt_translation(option, lang, text):
    return AnswerSchemaOptionTranslation.objects.create(
        option=option, language=lang, text=text,
    )


def _q_translation(question, lang, title, description=None):
    return QuestionTranslation.objects.create(
        question=question, language=lang, title=title, description=description,
    )


def _sec_translation(section, lang, title, description=None):
    return SectionTranslation.objects.create(
        section=section, language=lang, title=title, description=description,
    )


def _survey_translation(survey, lang, title, description=None, short_description=None):
    return SurveyTranslation.objects.create(
        survey=survey, language=lang, title=title,
        description=description, short_description=short_description,
    )


# ─────────────────────────────────────────────────────────────────────
# Survey 1: Basic Scored Exam — full anti-cheat, timed, auto-eval
# ─────────────────────────────────────────────────────────────────────
def create_survey_1():
    survey = _create_survey(
        title=f"{TAG}Basic Scored Exam",
        description="Timed exam with full anti-cheat, scoring, and locked answers.",
        survey_type="exam",
        display_option="by_question",
        is_timed=True,
        time_limit=timedelta(minutes=5),
        is_evaluable=True,
        evaluation_type="automatic_evaluation",
        use_score=True,
        enable_anti_cheat=True,
        lock_answers=True,
        randomize_questions=True,
        randomize_options=True,
    )
    _status(survey, "published")

    s1 = _section(survey, "General Knowledge", 1)

    q1 = _question(s1, "What is 2 + 2?", "radio", 1, is_required=True)
    _option(q1, "3", 1, score=0)
    _option(q1, "4", 2, score=10)
    _option(q1, "5", 3, score=0)
    _option(q1, "6", 4, score=0)

    q2 = _question(s1, "Capital of France?", "dropdown", 2, is_required=True)
    _option(q2, "London", 1, score=0)
    _option(q2, "Paris", 2, score=10)
    _option(q2, "Berlin", 3, score=0)

    q3 = _question(s1, "Select all prime numbers", "checkbox", 3, is_required=True)
    _option(q3, "2", 1, score=5)
    _option(q3, "3", 2, score=5)
    _option(q3, "4", 3, score=0)
    _option(q3, "6", 4, score=0)

    return survey


# ─────────────────────────────────────────────────────────────────────
# Survey 2: Classification + Recommendation Personality Assessment
# ─────────────────────────────────────────────────────────────────────
def create_survey_2():
    survey = _create_survey(
        title=f"{TAG}Personality Assessment",
        description="Classification-based assessment with recommendations.",
        survey_type="assessment",
        display_option="by_section",
        is_evaluable=True,
        evaluation_type="automatic_evaluation",
        use_score=False,
        use_classifications=True,
        use_recommendations=True,
    )
    _status(survey, "published")

    cl_a = _classification(survey, "Analytical", score=1)
    cl_b = _classification(survey, "Creative", score=2)
    cl_c = _classification(survey, "Social", score=3)

    # Section 1 — Work Style
    s1 = _section(survey, "Work Style", 1)

    q1 = _question(s1, "How do you solve problems?", "radio", 1)
    o1a = _option(q1, "Data analysis", 1, classification=cl_a)
    o1b = _option(q1, "Brainstorming", 2, classification=cl_b)
    o1c = _option(q1, "Ask colleagues", 3, classification=cl_c)

    _recommendation(survey, o1a, "Consider data science courses")
    _recommendation(survey, o1b, "Try creative workshops")
    _recommendation(survey, o1c, "Explore team leadership training")

    q2 = _question(s1, "Preferred work activity?", "radio", 2)
    _option(q2, "Spreadsheets", 1, classification=cl_a)
    _option(q2, "Design mockups", 2, classification=cl_b)
    _option(q2, "Team meetings", 3, classification=cl_c)

    # Section 2 — Communication
    s2 = _section(survey, "Communication", 2)

    q3 = _question(s2, "Email style?", "radio", 1)
    _option(q3, "Bullet points", 1, classification=cl_a)
    _option(q3, "Visual attachments", 2, classification=cl_b)
    _option(q3, "Personal stories", 3, classification=cl_c)

    q4 = _question(s2, "Conflict resolution approach?", "radio", 2)
    _option(q4, "Use logic and data", 1, classification=cl_a)
    _option(q4, "Find creative compromise", 2, classification=cl_b)
    _option(q4, "Mediate between parties", 3, classification=cl_c)

    return survey


# ─────────────────────────────────────────────────────────────────────
# Survey 3: Score-Range Actions (Form, Full Form)
# ─────────────────────────────────────────────────────────────────────
def create_survey_3():
    survey = _create_survey(
        title=f"{TAG}Score-Range Actions",
        description="Form with score-based actions and mixed question types.",
        survey_type="form",
        display_option="full_form",
        is_evaluable=True,
        evaluation_type="automatic_evaluation",
        use_score=True,
        use_actions=True,
    )
    _status(survey, "published")

    _action(survey, "Needs Improvement", "Score is below expectations.", lower_limit=0, upper_limit=10)
    _action(survey, "Satisfactory", "Score meets expectations.", lower_limit=11, upper_limit=20)
    _action(survey, "Excellent", "Score exceeds expectations.", lower_limit=21, upper_limit=30)

    s1 = _section(survey, "Assessment", 1)

    q1 = _question(s1, "Rate your experience", "radio", 1)
    _option(q1, "Poor", 1, score=0)
    _option(q1, "Average", 2, score=5)
    _option(q1, "Excellent", 3, score=10)

    q2 = _question(s1, "Select areas of strength", "checkbox", 2)
    _option(q2, "Communication", 1, score=5)
    _option(q2, "Technical skills", 2, score=5)
    _option(q2, "Leadership", 3, score=5)

    _question(s1, "Additional comments", "textarea", 3, is_required=False)
    _question(s1, "Years of experience", "number", 4, is_required=False)

    return survey


# ─────────────────────────────────────────────────────────────────────
# Survey 4: Grid Questions Exam
# ─────────────────────────────────────────────────────────────────────
def create_survey_4():
    survey = _create_survey(
        title=f"{TAG}Grid Questions Exam",
        description="Exam with radio grid and checkbox grid questions.",
        survey_type="exam",
        display_option="by_question",
        is_evaluable=True,
        evaluation_type="automatic_evaluation",
        use_score=True,
    )
    _status(survey, "published")

    s1 = _section(survey, "Skills Evaluation", 1)

    # Q1: Radio Grid — Rate each topic
    q1 = _question(s1, "Rate each topic", "radio_grid", 1, is_required=True)
    # Rows
    _option(q1, "Math", 1, is_row=True, is_column=False)
    _option(q1, "Science", 2, is_row=True, is_column=False)
    _option(q1, "English", 3, is_row=True, is_column=False)
    # Columns
    _option(q1, "Poor", 4, score=0, is_column=True, is_row=False)
    _option(q1, "Fair", 5, score=3, is_column=True, is_row=False)
    _option(q1, "Good", 6, score=7, is_column=True, is_row=False)
    _option(q1, "Excellent", 7, score=10, is_column=True, is_row=False)

    # Q2: Checkbox Grid — Select applicable skills
    q2 = _question(s1, "Select applicable skills per area", "checkbox_grid", 2, is_required=True)
    # Rows
    _option(q2, "Frontend", 1, is_row=True, is_column=False)
    _option(q2, "Backend", 2, is_row=True, is_column=False)
    _option(q2, "DevOps", 3, is_row=True, is_column=False)
    # Columns
    _option(q2, "JavaScript", 4, score=2, is_column=True, is_row=False)
    _option(q2, "Python", 5, score=2, is_column=True, is_row=False)
    _option(q2, "Docker", 6, score=2, is_column=True, is_row=False)

    return survey


# ─────────────────────────────────────────────────────────────────────
# Survey 5: Ending Option Early Termination
# ─────────────────────────────────────────────────────────────────────
def create_survey_5():
    survey = _create_survey(
        title=f"{TAG}Ending Option Termination",
        description="Assessment with ending option early termination (in-row).",
        survey_type="assessment",
        display_option="by_question",
        is_evaluable=True,
        evaluation_type="automatic_evaluation",
        use_score=True,
        allow_end_based_on_answer_repeat=True,
        answers_count_to_end=3,
        end_based_on_answer_repeat_in_row=True,
    )
    _status(survey, "published")

    s1 = _section(survey, "Skill Check", 1)

    for i in range(1, 7):
        q = _question(s1, f"Can you perform task #{i}?", "radio", i)
        _option(q, "I can do this", 1, score=10, ending_option=False)
        _option(q, "I need help", 2, score=5, ending_option=False)
        _option(q, "I cannot do this", 3, score=0, ending_option=True)

    return survey


# ─────────────────────────────────────────────────────────────────────
# Survey 6: Manual Evaluation (Essay + File + Date types)
# ─────────────────────────────────────────────────────────────────────
def create_survey_6():
    survey = _create_survey(
        title=f"{TAG}Manual Evaluation Portfolio",
        description="Curriculum with manual evaluation and file/text/date questions.",
        survey_type="curriculum",
        display_option="by_section",
        is_evaluable=True,
        evaluation_type="manual_evaluation",
        use_score=True,
    )
    _status(survey, "published")

    s1 = _section(survey, "Essay Questions", 1)
    _question(s1, "Describe your project", "textarea", 1, is_required=True)
    _question(s1, "Upload your portfolio", "file", 2, is_required=True)

    s2 = _section(survey, "Short Answers", 2)
    _question(s2, "Your role in the project?", "text", 1, is_required=True)
    _question(s2, "Project start date", "date", 2)
    _question(s2, "Submission deadline", "datetime", 3)
    _question(s2, "Preferred meeting time", "time", 4)

    return survey


# ─────────────────────────────────────────────────────────────────────
# Survey 7: Child Assessment (is_for_child + classifications)
# ─────────────────────────────────────────────────────────────────────
def create_survey_7():
    survey = _create_survey(
        title=f"{TAG}Child Developmental Milestones",
        description="Child assessment with classifications.",
        survey_type="survey",
        display_option="by_question",
        is_for_child=True,
        is_evaluable=True,
        evaluation_type="automatic_evaluation",
        use_score=True,
        use_classifications=True,
    )
    _status(survey, "published")

    cl_on_track = _classification(survey, "On Track", score=1)
    cl_needs = _classification(survey, "Needs Support", score=2)
    cl_advanced = _classification(survey, "Advanced", score=3)

    s1 = _section(survey, "Developmental Milestones", 1)

    q1 = _question(s1, "Can the child count to 10?", "radio", 1, is_required=True)
    _option(q1, "Yes, fluently", 1, score=10, classification=cl_advanced)
    _option(q1, "With some help", 2, score=5, classification=cl_on_track)
    _option(q1, "Not yet", 3, score=0, classification=cl_needs)

    q2 = _question(s1, "Can the child write their name?", "radio", 2, is_required=True)
    _option(q2, "Yes, independently", 1, score=10, classification=cl_advanced)
    _option(q2, "With guidance", 2, score=5, classification=cl_on_track)
    _option(q2, "Not yet", 3, score=0, classification=cl_needs)

    q3 = _question(s1, "Social interaction with peers?", "radio", 3, is_required=True)
    _option(q3, "Leads group activities", 1, score=10, classification=cl_advanced)
    _option(q3, "Participates well", 2, score=5, classification=cl_on_track)
    _option(q3, "Needs encouragement", 3, score=0, classification=cl_needs)

    return survey


# ─────────────────────────────────────────────────────────────────────
# Survey 8: Section Navigation with Jump
# ─────────────────────────────────────────────────────────────────────
def create_survey_8():
    survey = _create_survey(
        title=f"{TAG}Section Jump Navigation",
        description="Form demonstrating section jump navigation.",
        survey_type="form",
        display_option="by_section",
        is_evaluable=False,
    )
    _status(survey, "published")

    s1 = _section(survey, "Screening", 1, submit_action="next")
    q1 = _question(s1, "Are you a student?", "radio", 1)
    _option(q1, "Yes", 1)
    _option(q1, "No", 2)

    # Create sections 3 and 4 first so we can reference s4 as jump target
    s3 = _section(survey, "Professional Details", 3, submit_action="next")
    _question(s3, "Company name", "text", 1)

    s4 = _section(survey, "Contact Info", 4, submit_action="next")
    _question(s4, "Email address", "text", 1)

    s2 = _section(survey, "Student Details", 2, submit_action="jump", submit_action_target=s4)
    _question(s2, "University name", "text", 1)

    return survey


# ─────────────────────────────────────────────────────────────────────
# Survey 9: Anti-Cheat OFF Contrast Test (timed, but no anti-cheat)
# ─────────────────────────────────────────────────────────────────────
def create_survey_9():
    survey = _create_survey(
        title=f"{TAG}Anti-Cheat OFF Contrast",
        description="Timed exam with anti-cheat disabled — contrast test for Survey 1.",
        survey_type="exam",
        display_option="by_question",
        is_timed=True,
        time_limit=timedelta(minutes=10),
        is_evaluable=True,
        evaluation_type="automatic_evaluation",
        use_score=True,
        enable_anti_cheat=False,
        lock_answers=True,  # should be ignored when anti-cheat is off
    )
    _status(survey, "published")

    s1 = _section(survey, "General Knowledge", 1)

    q1 = _question(s1, "What is 2 + 2?", "radio", 1, is_required=True)
    _option(q1, "3", 1, score=0)
    _option(q1, "4", 2, score=10)
    _option(q1, "5", 3, score=0)
    _option(q1, "6", 4, score=0)

    q2 = _question(s1, "Capital of France?", "dropdown", 2, is_required=True)
    _option(q2, "London", 1, score=0)
    _option(q2, "Paris", 2, score=10)
    _option(q2, "Berlin", 3, score=0)

    q3 = _question(s1, "Select all prime numbers", "checkbox", 3, is_required=True)
    _option(q3, "2", 1, score=5)
    _option(q3, "3", 2, score=5)
    _option(q3, "4", 3, score=0)
    _option(q3, "6", 4, score=0)

    return survey


# ─────────────────────────────────────────────────────────────────────
# Survey 10: Multi-Language Survey (English + Arabic)
# ─────────────────────────────────────────────────────────────────────
def create_survey_10():
    survey = _create_survey(
        title=f"{TAG}Multi-Language Survey",
        description="Survey with English and Arabic translations.",
        survey_type="survey",
        display_option="by_section",
        is_evaluable=True,
        evaluation_type="automatic_evaluation",
        use_score=True,
    )
    _status(survey, "published")

    # The _create_survey already created an "en" translation; update it and add Arabic
    en_translation = survey.translations.first()
    en_translation.title = "Demographics Survey"
    en_translation.description = "A short demographics survey."
    en_translation.save()
    _survey_translation(survey, "ar", "استبيان البيانات الديموغرافية", "استبيان قصير للبيانات الديموغرافية.")

    s1 = _section(survey, "Demographics", 1)
    _sec_translation(s1, "en", "Demographics", "Basic demographic information.")
    _sec_translation(s1, "ar", "البيانات الديموغرافية", "معلومات ديموغرافية أساسية.")

    # Q1: Gender
    q1 = _question(s1, "Gender", "radio", 1, is_required=True)
    _q_translation(q1, "en", "Gender", "Select your gender.")
    _q_translation(q1, "ar", "الجنس", "اختر جنسك.")

    o1a = _option(q1, "Male", 1, score=0)
    _opt_translation(o1a, "en", "Male")
    _opt_translation(o1a, "ar", "ذكر")

    o1b = _option(q1, "Female", 2, score=0)
    _opt_translation(o1b, "en", "Female")
    _opt_translation(o1b, "ar", "أنثى")

    # Q2: Age Range
    q2 = _question(s1, "Age Range", "dropdown", 2, is_required=True)
    _q_translation(q2, "en", "Age Range", "Select your age range.")
    _q_translation(q2, "ar", "الفئة العمرية", "اختر فئتك العمرية.")

    o2a = _option(q2, "Under 18", 1, score=0)
    _opt_translation(o2a, "en", "Under 18")
    _opt_translation(o2a, "ar", "أقل من 18")

    o2b = _option(q2, "18-30", 2, score=5)
    _opt_translation(o2b, "en", "18-30")
    _opt_translation(o2b, "ar", "18-30")

    o2c = _option(q2, "31-50", 3, score=5)
    _opt_translation(o2c, "en", "31-50")
    _opt_translation(o2c, "ar", "31-50")

    o2d = _option(q2, "Over 50", 4, score=0)
    _opt_translation(o2d, "en", "Over 50")
    _opt_translation(o2d, "ar", "أكثر من 50")

    return survey


# ─────────────────────────────────────────────────────────────────────
# Command
# ─────────────────────────────────────────────────────────────────────

CREATORS = [
    ("Survey 1: Basic Scored Exam (anti-cheat, timed, auto-eval)", create_survey_1),
    ("Survey 2: Classification + Recommendation Personality", create_survey_2),
    ("Survey 3: Score-Range Actions (full_form, mixed types)", create_survey_3),
    ("Survey 4: Grid Questions Exam (radio_grid, checkbox_grid)", create_survey_4),
    ("Survey 5: Ending Option Early Termination (in-row)", create_survey_5),
    ("Survey 6: Manual Evaluation (essay, file, date types)", create_survey_6),
    ("Survey 7: Child Assessment (is_for_child, classifications)", create_survey_7),
    ("Survey 8: Section Jump Navigation", create_survey_8),
    ("Survey 9: Anti-Cheat OFF Contrast Test", create_survey_9),
    ("Survey 10: Multi-Language (EN + AR translations)", create_survey_10),
]


class Command(BaseCommand):
    help = "Seed 10 test surveys covering all solve/evaluate workflows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--truncate",
            action="store_true",
            help=f'Delete existing test surveys (translation title starts with "{TAG}") before seeding.',
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            if options["truncate"]:
                survey_ids = SurveyTranslation.objects.filter(
                    title__startswith=TAG
                ).values_list("survey_id", flat=True)
                deleted, _ = Survey.objects.filter(id__in=survey_ids).delete()
                self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing test survey objects."))

            for label, creator_fn in CREATORS:
                survey = creator_fn()
                self.stdout.write(self.style.SUCCESS(f"  [{survey.id}] {label}"))

        self.stdout.write(self.style.SUCCESS(f"\nDone — {len(CREATORS)} test surveys created."))

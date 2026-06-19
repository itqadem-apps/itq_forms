"""Generate a PDF report for a submitted UserSurvey."""
from __future__ import annotations

import math
from datetime import datetime

from io import BytesIO

from django.template.loader import render_to_string
from xhtml2pdf import pisa

from .models import (
    UserAction,
    UserAnswer,
    UserAnswerOption,
    UserQuestion,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)


# ── Colour helpers ──────────────────────────────────────────────────────

_COLORS = ["#4f46e5", "#6366f1", "#818cf8", "#a5b4fc", "#475569", "#64748b"]


def _color_for_index(i: int) -> str:
    return _COLORS[i % len(_COLORS)]


# ── Translation helper ─────────────────────────────────────────────────

def _t(translations: dict, field: str, lang: str = "default") -> str:
    """Pull a translated field from the JSON translations dict."""
    if not translations:
        return ""
    # Try requested lang first, then 'default', then first available
    for try_lang in [lang, "default"]:
        entry = translations.get(try_lang)
        if isinstance(entry, dict) and entry.get(field):
            return entry[field]
    # Fallback: first language that has the field
    for entry in translations.values():
        if isinstance(entry, dict) and entry.get(field):
            return entry[field]
    return ""


# ── Termination reason labels ──────────────────────────────────────────

_TERMINATION_LABELS = {
    UserSurvey.TERMINATION_COMPLETED: "Completed",
    UserSurvey.TERMINATION_TIME_EXPIRED: "Time expired",
    UserSurvey.TERMINATION_ENDING_OPTION: "Early termination",
}


# ── Build template context ─────────────────────────────────────────────

def _build_context(user_survey: UserSurvey, lang: str = "default") -> dict:
    """Build the full template context dict for a UserSurvey report."""

    # ── Survey metadata ──
    survey_title = _t(user_survey.translations, "title", lang) or f"Survey #{user_survey.id}"
    survey_desc = _t(user_survey.translations, "description", lang)
    survey_type = user_survey.survey_type or "assessment"
    survey_type_label = survey_type.replace("_", " ").title() + " Report"

    # ── User info ──
    user = user_survey.user
    user_name = ""
    user_initials = "?"
    user_id = user_survey.user_id or 0
    if user:
        first = getattr(user, "first_name", "") or ""
        last = getattr(user, "last_name", "") or ""
        user_name = f"{first} {last}".strip() or str(user)
        user_initials = (first[:1] + last[:1]).upper() or user_name[:1].upper()

    child_name = ""
    if user_survey.child:
        child_name = user_survey.child.name or ""

    # ── Submitted at ──
    submitted_at = ""
    if user_survey.submitted_at:
        submitted_at = user_survey.submitted_at.strftime("%b %d, %Y")

    # ── Score ring ──
    show_score = user_survey.use_score and user_survey.score is not None

    # Calculate max possible score from all MCQ options
    max_score = 0
    if show_score:
        questions = list(
            UserQuestion.objects.filter(user_survey=user_survey)
            .select_related("answer_schema")
            .order_by("section__order", "order")
        )
        for q in questions:
            if q.type in UserQuestion.SINGLE_SELECT_TYPES:
                opts = UserAnswerOption.objects.filter(schema__question=q)
                scores = [o.score or 0 for o in opts]
                max_score += max(scores) if scores else 0
            elif q.type in UserQuestion.MULTI_SELECT_TYPES + UserQuestion.GRID_TYPES:
                opts = UserAnswerOption.objects.filter(schema__question=q)
                max_score += sum(max(0, o.score or 0) for o in opts)

    score = user_survey.score or 0
    score_pct = round(score / max_score * 100) if max_score > 0 else 0

    # SVG ring math: r=54, circumference = 2*pi*54
    circumference = round(2 * math.pi * 54, 2)
    dash_offset = round(circumference * (1 - score_pct / 100), 2)

    # ── Action ──
    # title is a short label; description is admin-authored rich text (HTML).
    action_title = ""
    action_description = ""
    if user_survey.use_actions and user_survey.action_id:
        action = UserAction.objects.filter(id=user_survey.action_id).first()
        if action:
            action_title = _t(action.translations, "title", lang)
            action_description = _t(action.translations, "description", lang)

    # ── Classifications ──
    show_classifications = user_survey.use_classifications
    classifications = []
    if show_classifications:
        survey_clfs = list(
            UserSurveyClassification.objects.filter(user_survey=user_survey)
            .select_related("classification")
            .order_by("-count")
        )
        total_clf_count = sum(sc.count for sc in survey_clfs) or 1
        for i, sc in enumerate(survey_clfs):
            clf = sc.classification
            name = _t(clf.translations, "name", lang) if clf else f"Classification {i+1}"
            pct = round(sc.count / total_clf_count * 100)
            classifications.append({
                "name": name,
                "pct": pct,
                "color": _color_for_index(i),
            })

    # ── Recommendations ──
    show_recommendations = user_survey.use_recommendations
    recommendations = []
    if show_recommendations:
        survey_recs = list(
            UserSurveyRecommendation.objects.filter(user_survey=user_survey)
            .select_related("recommendation")
            .order_by("-count")
        )
        for sr in survey_recs:
            rec = sr.recommendation
            desc = _t(rec.translations, "description", lang) if rec else ""
            if desc:
                recommendations.append({"description": desc})

    # ── Answers ──
    answers_data = []
    all_answers = list(
        UserAnswer.objects.filter(user_survey=user_survey)
        .select_related("question", "question__answer_schema")
        .prefetch_related("selected_options", "question__answer_schema__options")
        .order_by("question__section__order", "question__order")
    )

    for idx, answer in enumerate(all_answers, start=1):
        q = answer.question
        if not q:
            continue

        q_title = _t(q.translations, "title", lang) or f"Question {idx}"
        item = {
            "number": f"{idx:02d}",
            "question_title": q_title,
            "score_display": "",
            "score_class": "",
            "border_class": "border-indigo",
            "display_type": "text",
            "answer_text": answer.answer or "",
            "options": [],
            "columns": [],
            "rows": [],
        }

        # Score display
        if show_score and answer.score is not None:
            # Determine max for this question
            q_max = 0
            if q.type in UserQuestion.SINGLE_SELECT_TYPES:
                opts = list(UserAnswerOption.objects.filter(schema__question=q))
                q_max = max((o.score or 0 for o in opts), default=0)
            elif q.type in UserQuestion.MULTI_SELECT_TYPES + UserQuestion.GRID_TYPES:
                opts = list(UserAnswerOption.objects.filter(schema__question=q))
                q_max = sum(max(0, o.score or 0) for o in opts)

            item["score_display"] = f"{answer.score}/{q_max} Points"
            if q_max > 0:
                ratio = answer.score / q_max
                if ratio >= 1:
                    item["score_class"] = "emerald"
                    item["border_class"] = "border-emerald"
                elif ratio > 0:
                    item["score_class"] = "amber"
                    item["border_class"] = "border-amber"
                else:
                    item["score_class"] = "rose"
                    item["border_class"] = "border-rose"
            else:
                item["score_class"] = "indigo"
                item["border_class"] = "border-indigo"
        elif not show_score:
            item["border_class"] = "border-slate"

        # Display type
        if q.type in UserQuestion.GRID_TYPES:
            item["display_type"] = "grid"
            schema = q.answer_schema if hasattr(q, "answer_schema") else None
            if schema:
                all_opts = list(schema.options.order_by("order"))
                columns = [o for o in all_opts if o.is_column]
                rows = [o for o in all_opts if o.is_row]
                selected_ids = set(answer.selected_options.values_list("id", flat=True))

                item["columns"] = [
                    {"id": c.id, "text": _t(c.translations, "text", lang) or f"Col {ci+1}"}
                    for ci, c in enumerate(columns)
                ]

                for ri, row in enumerate(rows):
                    # For grid, selected options with same row
                    selected_col_ids = set()
                    for sel in answer.selected_options.all():
                        if sel.is_column:
                            selected_col_ids.add(sel.id)
                    # Simpler: just check which columns are selected
                    item["rows"].append({
                        "text": _t(row.translations, "text", lang) or f"Row {ri+1}",
                        "selected_col_ids": selected_col_ids,
                    })

        elif q.type in UserQuestion.MCQ_TYPES:
            item["display_type"] = "options"
            schema = q.answer_schema if hasattr(q, "answer_schema") else None
            if schema:
                all_opts = list(schema.options.order_by("order"))
                selected_ids = set(answer.selected_options.values_list("id", flat=True))

                for opt in all_opts:
                    opt_text = _t(opt.translations, "text", lang) or "Option"
                    is_selected = opt.id in selected_ids
                    opt_score = opt.score or 0

                    if is_selected and show_score:
                        css_class = "selected-correct" if opt_score > 0 else "selected-incorrect"
                    elif is_selected:
                        css_class = "selected-neutral"
                    else:
                        css_class = ""

                    item["options"].append({"text": opt_text, "css_class": css_class})
        else:
            item["display_type"] = "text"

        answers_data.append(item)

    # ── Stats ──
    total_questions = len(all_answers)
    show_tab_switches = user_survey.enable_anti_cheat
    tab_switch_count = user_survey.tab_switch_count or 0
    termination_reason_label = _TERMINATION_LABELS.get(user_survey.termination_reason, "")

    generated_at = datetime.now().strftime("%B %d, %Y")

    return {
        "survey_title": survey_title,
        "survey_description": survey_desc,
        "survey_type_label": survey_type_label,
        "user_name": user_name,
        "user_initials": user_initials,
        "user_id": user_id,
        "child_name": child_name,
        "submitted_at": submitted_at,
        "show_score": show_score,
        "score": score,
        "max_score": max_score,
        "score_pct": score_pct,
        "circumference": circumference,
        "dash_offset": dash_offset,
        "action_title": action_title,
        "action_description": action_description,
        "show_classifications": show_classifications,
        "classifications": classifications,
        "show_recommendations": show_recommendations,
        "recommendations": recommendations,
        "answers": answers_data,
        "total_questions": total_questions,
        "show_tab_switches": show_tab_switches,
        "tab_switch_count": tab_switch_count,
        "termination_reason_label": termination_reason_label,
        "generated_at": generated_at,
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
    }


def generate_report_pdf(user_survey: UserSurvey, lang: str = "default") -> bytes:
    """Render the report template and return PDF bytes."""
    context = _build_context(user_survey, lang)
    html_string = render_to_string("user_surveys/report.html", context)
    buf = BytesIO()
    pisa_status = pisa.CreatePDF(html_string, dest=buf)
    if pisa_status.err:
        raise RuntimeError("PDF generation failed")
    return buf.getvalue()

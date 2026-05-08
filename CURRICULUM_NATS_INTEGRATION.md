# Curriculum NATS Integration

## Summary

`itq_assessments` now supports generic curriculum integration over NATS. External services can publish references from their own content to local assessment surveys or collections, then publish enrollment/access events that grant local `Usage` rows for users.

This keeps the integration service-agnostic. Courses can be the first producer, but any service can use the same contract by publishing on its own subject prefix.

## What Changed

- Added `curriculum_references` Django app.
- Added `CurriculumReference` model with:
  - `source_service`
  - `source_model`
  - `source_id`
  - optional `collection`
  - optional `survey`
  - `data`
- Added NATS handlers:
  - `handle_curriculum_reference_event`
  - `handle_curriculum_enrollment_event`
- Curriculum events are consumed automatically by the ASGI lifespan
  (see `app/messaging/runtime.py` + `app/messaging/registry.py`); no
  dedicated management command is required.
- Default subjects:
  - `*.curriculum_reference`
  - `*.curriculum_enrollment`

## Event Contracts

Reference upsert:

```json
{
  "source_model": "lesson",
  "source_id": "course-lesson-id",
  "collection_id": 123,
  "survey_id": 456,
  "data": {}
}
```

Enrollment/access grant:

```json
{
  "source_model": "lesson",
  "source_id": "course-lesson-id",
  "user_id": "keycloak-sub",
  "usage_limit": 1,
  "enrollment_id": "external-enrollment-id",
  "data": {}
}
```

`source_service` is optional. If omitted, it is derived from the subject prefix, so `courses.curriculum_reference` resolves to `courses`.

## Behavior

- Reference events create or update local `CurriculumReference` rows.
- Enrollment events resolve the external source through `CurriculumReference`.
- For each matching reference with a survey, the handler creates or updates a `Usage` row.
- Enrollment events do not create `UserSurvey` rows. The user still enrolls through the existing assessment flow, which consumes the granted usage.
- `usage_limit` defaults to `1`; `0` means unlimited.

## Verification

Static compilation passed:

```bash
.venv/bin/python -m py_compile app/messaging_contract.py curriculum_references/models.py curriculum_references/consumer.py app/messaging/handlers/curriculum_events.py tests/test_curriculum_references.py
```

Local pytest could not be run because `pytest` is not installed in the available Python environments. `manage.py check` is also blocked locally by a missing `pkg_auth.authorization` dependency in `.venv`.

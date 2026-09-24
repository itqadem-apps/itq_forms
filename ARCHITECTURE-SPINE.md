---
name: 'forms'
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: 'a Django project, unlike its ports-and-adapters siblings'
scope: 'invariants binding the forms service'
status: draft
created: '2026-08-28'
updated: '2026-09-24'
binds: []
sources: []
companions: []
---

# Architecture Spine — forms

## Design Paradigm

A Django project, and the exception in a backend otherwise built ports-and-adapters. It is organised as Django apps — `accounts/`, `assessment_exports/`, `classifications/`, `external_references/` — around a conventional `app/` settings package with a GraphQL surface (`schema_common.py`), its own permission catalogue and database routers. A reader arriving from any sibling service will find none of `domain/ app/ infra/ interface/` here, and that difference is structural rather than an oversight.

## Inherited Invariants

These are the estate's, listed by their original ids and **not** re-keyed here — a second key
for one decision is the collision the namespace grammar exists to prevent. Where anything below
disagrees with one of these, the inherited decision wins and the disagreement is a conflict to
surface, not a local override.

- `estate:AD-1` — the knowledge base is a routing aid, never the authority
- `estate:AD-2` — a decision lives in the repo it binds
- `estate:AD-3` — every citation is namespaced
- `estate:AD-4` — board automation never moves a card between lists
- `estate:AD-5` — human requests enter through a separate board, and only through triage
- `estate:AD-6` — courses is the system of record for live cohorts
- `estate:AD-7` — one NATS subject grammar: `<service>.<aggregate_type>`, event variant in the payload
- `estate:AD-8` — two ACL database roles: SELECT-only at runtime, write-capable only at deploy

## Invariants & Rules

### AD-1 — A survey's primary locale is stored on the survey, never derived

- **Binds:** `backend/itq_forms`, `frontend/layers/lyr-surveys`
- **Prevents:** the backend and the authoring UI each deciding for themselves which language a
  survey is "really" written in, and disagreeing. Every translatable row keeps its own legacy
  column beside its translation rows, and at enrolment `_build_translations`
  (`user_surveys/services.py`) merges that column into **one** language's key — whichever the
  backend calls primary — wherever the translation for it is null or empty. The admin builder
  mirrors the same legacy columns from whichever language **it** calls primary. Where the two
  names differ, a learner reading language X is served text written in language Y under X's key:
  no error, no empty field, nothing to notice. It was reachable because the backend derived the
  primary from `survey.translations.first()` — `ORDER BY id` over a `uuid4` primary key, which
  names a language nobody chose and a different one per survey.
- **Rule:** the primary locale is the value of **`Survey.primary_language`**, falling back to
  `Survey.PRIMARY_LANGUAGE_FALLBACK` (`"default"`) where it is unset. Backend: read it through
  `Survey.primary_locale`, the single accessor every consumer routes through — the snapshot, the
  GraphQL type and `Survey.title`/`Survey.language` all go via it, and nothing queries the
  translations to answer this question. Frontend: read `Survey.primaryLanguage` over GraphQL. Do
  **not** derive a primary client-side, not even by a rule that matches the backend's today. No
  second derivation anywhere.
- **Why stored and not derived:** a derived primary — the alphabetically first authored language,
  say — moves the moment an author adds an earlier one, and that is not self-healing here.
  `create_survey_snapshot` deep-copies the survey into each learner's own rows at enrolment and
  **freezes** them; no later edit to the survey reaches a learner already enrolled. So between a
  move and a re-save of every affected row, each new enrolment permanently files the old
  language's body text under the new language's key, unreachable by any later fix. Both sides
  deriving the value identically does not help: at snapshot time they agree on the label and the
  text is still the other language's. The repair that would have closed the window is not
  available either — `SectionTranslation`, `QuestionTranslation` and `AnswerSchemaOptionTranslation`
  have no rows at all today (that absence is the gap the surveys builder exists to close), so
  mirroring the legacy columns "from the new primary's translation" would have been a no-op for
  exactly the rows at risk. A stored value moves only when someone moves it, which makes the move
  an act that can be paired with a repair.
- **Accepted costs:** one column and two migrations rather than a `Meta.ordering` line, and a
  write path that has to keep the column honest — `SurveyTranslation.save()` claims it for the
  first language authored, and a `bulk_create` bypasses that and must set it itself. Existing
  rows were backfilled (`surveys/migrations/0041`) with the language the old
  `.first()`/`ORDER BY id` selector already returned, so the migration is behaviour-preserving by
  construction: no survey's primary moves as it lands. `tools/audit_primary_locale.sql` states
  that selector in SQL.
- **History:** first ruled the other way — `ordering = ["language"]` on the eight `*Translation`
  models, taking mutability as an acceptable cost because no translation model carries a
  `created_at` to order by instead. Reversed on 2026-09-24 once the interaction with frozen
  snapshots was spelled out: a mutable primary is not merely inconvenient for a value that gets
  copied into per-learner records and never revisited. Recorded here so the decision is not
  re-litigated from the implementation-cost angle alone, which is the angle that got it wrong.

## Deferred

Not yet enumerated. The gaps this repo knows it owes are recorded here as they are noticed —
a named gap is worth more than silence, because it stops the next reader concluding the
question was never asked.

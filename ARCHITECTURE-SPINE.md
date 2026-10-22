---
name: 'forms'
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: 'a Django project, unlike its ports-and-adapters siblings; an authored template materialised per learner at enrolment'
scope: 'invariants binding the forms service, including the survey flow engine — answer-conditional routing, optional sections, and the scoring that branching makes ambiguous — and the builder''s authoring writes: soft delete, flatten, insert-after and import'
status: draft
created: '2026-08-28'
updated: '2026-10-18'
binds:
  - estate:AD-2
  - estate:AD-3
  - estate:AD-8
  - estate:AD-13
  - estate:AD-14
  - estate:AD-18
  - estate:AD-22
  - estate:AD-23
sources:
  - .agent/planning/briefs/brief-itqadem-2026-10-04/brief.md
  - .agent/planning/briefs/brief-itqadem-2026-10-04/addendum.md
companions: []
---

# Architecture Spine — forms

## Design Paradigm

A Django project, and the exception in a backend otherwise built ports-and-adapters. It is organised as Django apps — `accounts/`, `assessment_exports/`, `classifications/`, `external_references/` — around a conventional `app/` settings package with a GraphQL surface (`schema_common.py`), its own permission catalogue and database routers. A reader arriving from any sibling service will find none of `domain/ app/ infra/ interface/` here, and that difference is structural rather than an oversight.

### The flow engine's shape: template and snapshot

The authored tree (`Survey` → `Section` → `Question` → `AnswerSchema` → `AnswerSchemaOption`) is
a template nobody answers. At enrolment the whole tree is deep-copied into a parallel per-learner
tree (`UserSurvey` → `UserSection` → `UserQuestion` → `UserAnswerSchema` → `UserAnswerOption`),
and every attempt is read and written against that copy. Per-learner divergence is therefore
already the native shape of the schema: a per-learner path needs no new storage and no new copy
machinery, only routing columns riding the copy that already happens.

| Layer | Lives in | Owns |
| --- | --- | --- |
| authored template | `surveys/` | the survey an author builds; the only writer of the shared schema's DDL |
| learner snapshot | `user_surveys/` | one materialised copy per enrolment, and every answer |
| GraphQL edge | `*/schemas/`, `*/types/`, `*/inputs.py` | the admin and solver API surface |
| messaging | `app/messaging/` | JetStream publication and consumption |

```mermaid
graph LR
  AUTH[surveys<br/>authored template] -->|deep copy at enrolment| SNAP[user_surveys<br/>learner snapshot]
  SNAP --> ANS[answers + scoring]
  EDGE[GraphQL edge] --> AUTH
  EDGE --> SNAP
  SOLVER[lyr-surveys solver] -->|consumes only| EDGE
```

## Inherited Invariants

`estate:AD-1` through `estate:AD-23` bind here read-only, except `estate:AD-6`, `estate:AD-10`
and `estate:AD-11`, which name other services. They are not re-keyed here. Where anything below
disagrees with one of them, the inherited decision wins and the disagreement is a conflict to
surface, not a local override. `backend` carries no decisions of its own.

Load-bearing in this scope — the rest bind without shaping anything below:

| Inherited | From parent | Binds here |
| --- | --- | --- |
| `estate:AD-2` | estate spine | A decision binding only `itq_forms` is an `AD` here, reviewed with this repo's code and pinned at its ref. A decision `itq_forms` and `itq_surveys` must *agree* on is an estate call — the ordering scope in `forms:AD-4` was one, and is pinned as `estate:AD-19`. |
| `estate:AD-3` | estate spine | Every citation here is namespaced. Every spine in the estate reaches its own first decision, so a bare id is unresolvable. |
| `estate:AD-8` | estate spine | Two ACL database roles: SELECT-only at runtime, write-capable only at deploy. `itq_forms` routes the ACL database in `app/db_routers.py`, so a flow evaluation may not write through that connection. |
| `estate:AD-13` | estate spine | One declarant per stream prefix: forms creates FORMS only and never declares USERS, ORDERS or TAXONOMY — `forms:AD-26`. |
| `estate:AD-14` | estate spine | N>1 replicas. Flow evaluation holds no in-process state — see `forms:AD-17`. Relays coexist through a held `SKIP LOCKED` claim (clause 2) and streams are created if absent, never updated (clause 3) — `forms:AD-26`. |
| `estate:AD-18` | estate spine | A story reaches the build board whole and the build reads the story; no task is derived from this spine's epics. |
| `estate:AD-22` | estate spine | Every durable declares retry limits and the relay stamps `Nats-Msg-Id` — the precondition for running the relay and consumers apart from web, see `forms:AD-26`. |
| `estate:AD-23` | estate spine | A multi-worker server starts no messaging runtime, which is why web runs `--workers 2` with none — `forms:AD-26`. |

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
- **Default and create rule (ruled 2026-09-29):** the column defaults to **`ar`**
  (`Survey.PRIMARY_LANGUAGE_DEFAULT`, ORM-level only, `surveys/migrations/0043`). `create_survey`
  sets the primary in the same INSERT: an explicit `primary_language` wins; else `ar` if the
  create carries an `ar` translation; else the first translation's language; else `ar`. Not the
  first translation alone — the admin form sends `[en, ar]` in locale order. `0044` moved every
  survey with no `UserSurvey` to `ar`; a survey with any enrolment keeps its primary, and the
  enrolled non-`ar` ones await a per-survey ruling (`tools/audit_primary_locale.sql` E).
- **Accepted costs:** one column and two migrations rather than a `Meta.ordering` line, and a
  write path that has to keep the column honest — `create_survey` sets it by the rule above,
  `SurveyTranslation.save()` claims only a column left explicitly null, and a `bulk_create`
  bypasses both and must set it itself. Existing
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
  On 2026-09-28 (`0042`, v0.0.69) an `en` column default pre-empted the save-time claim, so every
  builder-created survey was filed under `en` whatever it was written in; replaced on 2026-09-29
  by the Arabic default and create rule above.

### AD-2 — The authored tree is a template; the learner's snapshot is the system of record for an attempt

- **Binds:** all flow evaluation, scoring and solver reads.
- **Prevents:** an attempt being evaluated against the author's current tree, so that editing a
  live survey silently changes the path of a learner already part-way through it.
- **Rule:** every read and write during an attempt resolves against the learner's own
  `UserSurvey` tree. Flow evaluation never reads `surveys/` rows. A survey edited after a learner
  enrols does not alter that learner's attempt. [ADOPTED — this is how enrolment already works.]

### AD-3 — Routing lives on the answer option, in two named columns

- **Binds:** the flow schema, the enrolment copy, and every mutation that authors an edge.
- **Prevents:** a second, parallel copy mechanism — a flow table the enrolment deep-copy does not
  know about — and, equally, two stories adding differently-shaped columns to the same table.
- **Rule:** an edge is exactly two columns on `AnswerSchemaOption`, mirrored on
  `UserAnswerOption`:
  - `flow_action`, a non-null stored string enum whose members are exactly `fall_through`,
    `go_to` and `terminate`, defaulting to `fall_through`. Fall-through is always stored
    explicitly and is **never** represented by null.
  - `flow_target`, a nullable foreign key to `Question` (`UserQuestion` on the snapshot), non-null
    **if and only if** `flow_action` is `go_to`.

  `go_to` and `terminate` are refused on a schema that admits more than one selected option, so
  one answer always yields one edge; a question with no options (free text, calculation) falls
  through. There is no separate edge table. The enrolment copy remaps `flow_target` onto the learner's own
  rows, the way the `Section.submit_action_target` self-FK is already remapped
  (`user_surveys/services.py:190-195`) — that is a section→section remap and this one is
  option→question, so the mechanism transfers but the code does not.

### AD-4 — Every question carries a survey-wide position, assigned by one function; sections are placed by position

- **Binds:** question ordering, `Question.Meta.ordering`, the reorder mutation, the backfill
  migration, section placement, and the forward-only check in `forms:AD-5`.
- **Prevents:** a sectionless question having no position and therefore no place in the order the
  flow falls through along — three independent renumber implementations (save path, reorder
  mutation, backfill) producing different 1..N sequences for the same survey — and a section
  whose questions are scattered, which no renderer can head once.
- **Rule:** `order` is assigned and renumbered across `survey_id`, for every question, whether or
  not it has a section. `Question.Meta.ordering` becomes `["order"]`. That one order is the
  authority, and sections are placed by it:
  - a section's questions are **contiguous** in survey-wide order; a write that would leave a
    section non-contiguous is refused with a named field error;
  - a section's position derives from its first question, and its heading renders immediately
    before that question;
  - sectionless questions sit between sections, never inside one;
  - moving a question across a section boundary changes its section — the reorder input names the
    destination section (or none) explicitly, and contiguity is checked after the write.

  Sections constrain nothing else: an edge may target any question in the survey. The
  `Question.section` foreign key is kept as the membership record, so no foreign-key migration
  runs through the cascading author-side keys `forms:AD-9` protects.

  **One function owns the renumber** — `renumber_questions(survey_id)` — and the save path, the
  reorder mutation and the backfill migration all call it. Its key is `(order, id)`; `Section.order`
  is rewritten by the same function to rank sections by their first question, with sections that
  hold no question placed after all others in their prior `order`. The backfill alone
  seeds `order` from the legacy key `(section.order nulls last, question.order, id)`. No other code
  assigns `order`.
- **Cross-service scope, ruled and enacted.** The estate ruled that `itq_surveys` adopts
  survey-wide scope, pinned as `estate:AD-19`; `surveys:AD-9` and `surveys:AD-17` were amended to
  match (`backend` `ed147dd`). Nothing in `itq_forms` waits on it any longer. The three carve-outs
  `estate:AD-19` left open wait on the `itq_surveys` build, which is deferred until this one
  finishes — see Deferred.

### AD-5 — An edge is forward-only, enforced by one predicate at every write

- **Binds:** edge mutations, reorder mutations, the enrolment copy, the ordering backfill.
- **Prevents:** a cycle. `forms:AD-6`'s evaluator depends on the forward-only guarantee to walk a
  path without loop detection, so one backward edge is not a bad route — it is a hung request
  thread. Equally prevents two surfaces each implementing their own comparison and disagreeing on
  a request that moves a question *and* edits an edge.
- **Rule:** an edge is valid only while its target's survey-wide position is greater than its
  source question's — survey-wide position on the author's tree, the learner's snapshot order
  (`UserQuestion.order`) on the copy. **One predicate owns this** — `assert_forward_only`, taking a survey or a learner snapshot and
  evaluated against the orders **as they will be after the write** — and the edge mutation, the reorder
  mutation, the enrolment copy and the ordering backfill all call it. No caller reimplements the
  comparison. A violation is refused with a named field error, never silently stored. Because the
  graph cannot contain a cycle, evaluation performs no cycle detection and no runtime loop guard.

### AD-6 — The server decides the next question, and says so in one shape

- **Binds:** the answer mutation, `should_terminate`, the solver in `lyr-surveys`.
- **Prevents:** the routing rule existing in two codebases and drifting — and the subtler failure
  of the write path and the poll path speaking two different vocabularies for *why an attempt
  ended*, against a solver that is permitted to cache what it was told.
- **Rule:** advancing an attempt returns **one named result type**: either the next question, or
  an ended marker carrying a reason from a single closed enum — `routing_terminate`,
  `ending_threshold`, `fallthrough_complete`, `force_terminated`. `should_terminate` returns a
  reason from that same enum. A nullable next-question field with no reason is not a legal shape.
  On the answer mutation the result is the `advance` field of the answer it already returns, so
  its return type does not change. The stored `termination_reason` keeps its values and the API
  maps them onto the enum (`completed` → `fallthrough_complete`, `time_expired` →
  `force_terminated`, `ending_option` → `ending_threshold`); `routing_terminate` is stored as is.

  Going back is a navigation, not a decision: the solver may return to any question the server
  has placed on the current path (`forms:AD-19`), and re-answering it is an ordinary advance whose
  result the solver follows. The solver navigates to what it is given and never derives the next question from the snapshot,
  even though the snapshot contains every edge. This is a consumer contract on `lyr-surveys`, not
  a shared decision — it constrains only what a consumer may do with this service's output, and so
  does not reach `estate:AD-2`'s bar for an estate call the way `forms:AD-4` does.

### AD-7 — A routing terminate and the ending-option threshold are distinct, and terminate wins

- **Binds:** `flow_action = terminate`, `ending_option`, `count_of_ending_options`,
  `answers_count_to_end`, `should_terminate`.
- **Prevents:** two different intents collapsing into one column. `ending_option` is a *scored
  cutoff* — options are counted and the attempt ends only once the count reaches the survey's
  threshold. A routing terminate is an authored hard stop at one answer. Overloading either with
  the other would make one routing terminate change the behaviour of every ending option in the
  survey, because the threshold is survey-wide.
- **Rule:** `flow_action = terminate` is stored separately and `ending_option` is left exactly as
  it is. Where one option carries both, the routing terminate wins and the attempt ends
  immediately with reason `routing_terminate`: a reached hard stop is not undone by a threshold
  that has not been met. A routing terminate is decided on the write path, not discovered by a
  later `should_terminate` poll.

### AD-8 — Fallthrough past the last question completes the survey

- **Binds:** flow evaluation's terminal case.
- **Prevents:** an undefined end state when an option falls through and no question follows in
  order — the case every fallthrough path eventually reaches.
- **Rule:** `fall_through` advances to the next question in the learner's snapshot order
  (`UserQuestion.order`, which is survey-wide order unless `forms:AD-12` shuffled it); when none remains,
  the attempt completes with reason `fallthrough_complete`, exactly as reaching the end of the
  last section does today. An author is never obliged to draw an explicit terminate to end a path.

### AD-9 — Reachability is the only source of hiding, and the hidden-section carve-outs go with the flag

- **Binds:** question visibility, `Section.is_hidden`, and every query that filters on it.
- **Prevents:** two independent hiding mechanisms whose interaction nobody has defined — and the
  quieter failure of retiring the flag while the queries that read it stand, which is what renders
  9 published assessments at 0% in the PDF today (`user_surveys/pdf_service.py:101-104`, shipped
  v0.0.75).
- **Rule:** a question is shown if and only if the flow reached it. No element carries a
  visibility condition and no setting hides a section. `Section.is_hidden` is retired, and every
  carve-out that reads it is removed in the same release — at minimum the PDF's
  `.exclude(section__is_hidden=True)` and the solver's `isHidden` handling in
  `lyr-surveys/app/composables/solve/useSolveSteps.ts:104-122`, which is dead code with no caller
  **and the only place that already honours the flag**, so retiring the flag without it leaves a
  trap rather than a regression.

  Each hidden section's questions move to `section=null`. **The section rows are not deleted:**
  `Question.section` is `on_delete=CASCADE`, so dropping a `Section` row would cascade away the
  very questions the migration intends to preserve. (`AnswerSchema.section` and
  `AnswerSchemaOption.section` are already nullable `SET_NULL` and follow the question to null.)
  The migration ships under `forms:AD-14`.

### AD-10 — Score basis is declared per assessment; an unreached answer does not score, an unreached calculation still computes

- **Binds:** scoring, result rendering, the PDF export.
- **Prevents:** two learners on different paths being scored against different denominators with
  no declared basis — and, separately, a later retrofit of the answer/calculation split, which
  would be a data migration over historic attempts.
- **Rule:** each assessment declares one basis: `answered`, `reached` or `all`, defaulting to
  `reached`. Under `answered` and `reached` a question the flow did not reach does not count; an
  unreached **calculation** still computes and still stores. A force-terminated attempt honours
  the declared basis with no special case. The split exists from the first migration. Because no
  survey in production carries a flow, `reached` and `all` are identical for every existing
  survey and the default is a no-op there.

### AD-11 — Flow is unavailable on `full_form`, and switching to it is refused

- **Binds:** the display option, the flow mutations.
- **Prevents:** authored routing that silently does nothing — which is exactly what the present
  unconditional section jump already is.
- **Rule:** `full_form` renders every question at once and has no step for an edge to land on, so
  flow is unavailable there. Switching an assessment that carries a flow to `full_form` is refused
  with a named error rather than leaving the flow dormant.

### AD-12 — Shuffle keeps the flow's anchors in place, and a shuffled step is never empty

- **Binds:** `randomize_questions`, the enrolment shuffle (`user_surveys/services.py:323-334`,
  which this replaces), the shuffle setting.
- **Prevents:** an author having to mark which questions are safe to shuffle and getting it wrong;
  a shuffle that changes **what an edge skips** — an edge also means "skip everything between here
  and the target", and moving a question into or out of that stretch silently reroutes it, which
  the middle mode as first written still allowed; a learner refused at enrolment because a shuffle
  pointed an edge backwards; and the documented randomisation-plus-hiding failure, where a step
  whose every question is unreached renders blank (`surveyjs/survey-library#9817`).
- **Rule:** a question is an **anchor** if any edge starts from one of its options or targets it.
  Anchorship is computed from the graph and is never a stored or authored field. Anchors keep
  their place; every other question shuffles only among the slots held by its own section (no
  section counts as one group) within its **gap** — between the adjacent anchors on either
  side — so sections stay contiguous (`forms:AD-4`).
  What each edge skips is therefore exactly what the author drew, for every learner, and the
  enrolment copy's `assert_forward_only` always passes.

  All three modes stay: shuffle all, shuffle only questions no edge touches (the default), and no
  shuffle. On a survey without a flow there are no anchors and "all" shuffles every question
  within its section group; on a
  survey with a flow "all" and the default coincide, and the builder says so. The shuffle runs
  once at enrolment and the order is locked for the attempt, so going back (`forms:AD-19`) is
  stable. Option shuffle (`randomize_options`) is unaffected. A step is presented only when the server
  issues a question in it (`forms:AD-6`), so a step the path skips is never presented empty. The shuffle's own `section__isnull=False` filter is removed by
  the release that makes sections optional.

### AD-13 — Required validation and result inclusion are scoped to the question, never to section membership

- **Binds:** `finish_assessment`'s required check, the results answer set.
- **Prevents:** an author marking a sectionless question required and getting neither enforcement
  nor a warning, and a sectionless question's answer silently vanishing from the results. Both
  exemptions exist today but are unreachable; making sections optional makes them live in the same
  release.
- **Rule:** no query that decides whether a question is enforced, scored or rendered may filter on
  section membership. Concretely that is `user_surveys/services.py:520`'s `section__isnull=False`
  on the required check and `:448`'s `exclude(question__section__isnull=True)` on the answer set,
  but the rule binds the invariant, not those two lines. The existing carve-out for a forced
  termination is unchanged: it remains guarded by the completion reason.

### AD-14 — Learner-data migrations are ordered, dry-run first, one per release

- **Binds:** the `is_hidden` retirement, the survey-wide ordering backfill, and any later
  migration over attempt data.
- **Prevents:** discovering the blast radius in production — every push of `itq_forms` main is a
  real release, so there is no quiet revert — and the subtler failure of the two migrations
  landing in either order and permanently producing different `order` sequences for the same
  survey, which neither migration's own counts would reveal.
- **Rule:** the two learner-data migrations in this epic are **ordered**: the survey-wide
  ordering backfill ships first, the `is_hidden` retirement second — so a hidden section's
  questions already hold their place when they lose their section, and the retirement changes
  only `section`. Each is preceded by a
  management command with `--dry-run`, reviewed before the migration ships; the backfill's dry run
  reports the resulting 1..N sequence per affected survey, not only counts. Data migrations ship
  in their **own** release, separate from the schema change and the feature code, and each carries
  a documented reversal.

  The ordering backfill also renumbers every **open** (unsubmitted) learner snapshot by
  `(UserSection.order nulls last, UserQuestion.order, id)` — which keeps a shuffled attempt's
  in-section order and makes its sections contiguous — so the snapshot order `forms:AD-5`,
  `forms:AD-8` and `forms:AD-18` read is defined for attempts already in flight. Submitted
  snapshots are not touched. The snapshot needs no *schema* migration: `UserQuestion.section`, `UserAnswerSchema.section`
  and `UserAnswerOption.section`/`.question` are **already** nullable. Making sections optional is
  an author-side nullability change.

### AD-15 — The legacy section jump is refused at the API, not dropped in this work

- **Binds:** `Section.submit_action`, `submit_action_target`, `SectionInput`.
- **Prevents:** a dead setting remaining authorable while the feature that replaces it ships.
- **Rule:** the API rejects `jump` and a non-null `submit_action_target` with a named field error.
  The columns stay; dropping them is deferred.

### AD-16 — Existing surveys do not change behaviour, and three author settings is the ceiling

- **Binds:** every default this epic introduces, and any later proposal to add a setting.
- **Prevents:** a release that silently re-scores or re-sequences the surveys live today — and the
  slower failure where every unresolved decision becomes a switch no author understands.
- **Rule:** a survey that carries no flow behaves exactly as it does today, at every default. The
  author-facing surface this epic adds is exactly two settings — shuffle interaction and score
  basis — alongside the existing display option; a fourth needs a forcing reason recorded as a new
  `AD`, not a story's judgement.

### AD-17 — Reachedness is recorded and recalculated, never replayed at scoring; evaluation holds no in-process state

- **Binds:** the answer write, scoring under `forms:AD-10`, the evaluator. [DERIVED —
  `estate:AD-14`.]
- **Prevents:** two compliant readings of `forms:AD-10` producing different denominators for the
  same attempt; a scoring-time replay that cannot place a calculation question at all, yet
  `forms:AD-10` requires one to compute; a stale reached flag surviving a learner going back and
  changing branch; and a learner's path depending on which replica served the request.
- **Rule:** reachedness is `UserQuestion.on_path`, stored on the learner's own row and
  **recalculated on every answer write** for the questions downstream of the one written, by the
  walk `forms:AD-19` defines — including the first question and every calculation it passes. `forms:AD-10`'s basis reads only those flags; no code
  replays the flow at scoring time. Evaluation is otherwise a pure function of the stored snapshot
  and the answer being written — no cursor, cache or partial path held in process between
  requests.

### AD-18 — The solver renders one flat ordered list, with section headings inserted by position

- **Binds:** the solve payload, every `lyr-surveys` solve mode, the PDF and results ordering.
- **Prevents:** a sectionless question being unrenderable because the solver groups strictly by
  section — and each solve mode inventing its own way to place a heading.
- **Rule:** the solve payload is one list of the learner's questions in snapshot order, each
  carrying its section (or none) and its `on_path` flag; a section heading is rendered before the
  first question of each contiguous run (`forms:AD-4`). No renderer groups by section.
  `by_question` makes each question a step; `by_section` makes each section's run a step and each
  sectionless question its own step, rendering only on-path questions as answers land. The
  existing `SolveQuestions` query, which has no caller, is not the basis.

### AD-19 — Every answered branch is kept until the attempt ends; the current path is walked, and the end deletes answers off it

- **Binds:** the answer write, going back, forced termination, submission, `forms:AD-17`.
- **Prevents:** a learner losing answers by peeking down a branch and coming back; two
  implementations disagreeing on which answers count; and answers from an abandoned branch leaking
  into a submitted result.
- **Rule:** nothing is deleted while an attempt is open. The **current path** is the walk from the
  first question in snapshot order to the end of the snapshot. At each question an answered option
  whose `flow_action` is `go_to` continues at its `flow_target`, and one whose `flow_action` is
  `terminate` ends the path there; **every other case falls through** to the next question in
  snapshot order (`forms:AD-8`) — a `fall_through` option, a question left blank (required or not,
  routing options or not), a question with no options, and a calculation. A blank question never
  stops the walk, so a survey carrying no flow has every question on its path, as today
  (`forms:AD-16`). Questions on that walk carry `on_path = true`, everything else `false`; one
  function owns the walk and both the answer write and submit call it. A learner may go back to any
  on-path question and re-answer it; answers on the branch they leave stay stored but off-path.
  **At every terminal transition** — submit, `routing_terminate`, `ending_threshold`,
  `force_terminated`, `fallthrough_complete` — the same function prunes: answers on questions with
  `on_path = false` are deleted; the `UserQuestion` rows and every calculation result are kept. A
  forced termination prunes against the current path.

  The advance result (`forms:AD-6`) is the walk's own output: the next on-path question after the
  one just written (already answered or not), or the ended marker when the path ends there. The
  evaluator and the walk are one function, so they cannot disagree after a go-back.

### AD-20 — A call that does not exist today is REST; existing calls and listings stay GraphQL

- **Binds:** every endpoint this epic adds or changes, and the solver's calls to them.
- **Prevents:** each story choosing its own transport, and an existing GraphQL call being
  rewritten as REST merely because the feature touches it.
- **Rule:** an endpoint that does not exist today is a plain Django view guarded by `pkg_auth`'s
  `require_permission`, behind the `LoggingIdentityMiddleware` and `OptionalAuthContextMiddleware`
  already in `app/settings.py`, and refuses with `pkg_auth`'s 401/403. A **listing** endpoint stays
  GraphQL even when new. An existing call keeps its transport when this epic extends it: the
  solver's load (`forms:AD-18`), the answer mutation (`forms:AD-6`, by gaining the `advance` field on the answer it returns) and
  submit (`forms:AD-19`) stay GraphQL and change in place, for every survey. No new dependency (django-ninja, DRF) is adopted
  without asking first. `forms:AD-6`'s result type and the named-field-error convention apply to a
  REST body unchanged.

  **Builder authoring calls stay GraphQL** (amended 2026-10-12). A *screen* is one admin page
  route; the builder screen is `/build`. Every call that screen makes stays GraphQL even when it is
  new — flatten (`forms:AD-23`), import and insert-after (`forms:AD-24`) — rather than splitting one
  screen across both APIs. The REST rule above binds the solver's new calls and any new screen.

### AD-21 — Builder deletes are soft, and the default manager sees only live rows

- **Binds:** `Section`, `Question`, `AnswerSchema`, `AnswerSchemaOption`, their delete mutations,
  `copy_question` and `duplicate_survey`, and every read of them — builder, GraphQL types, solve
  payload (`forms:AD-18`), enrolment copy (`forms:AD-2`), `renumber_questions` and
  `live_survey_questions` (`forms:AD-4`), `_placed_sequence`, anchors (`forms:AD-12`), media access,
  results.
- **Prevents:** a mistaken delete being unrecoverable — the builder autosaves, and a section's hard
  delete cascades its questions, schemas and options — and one read forgetting a filter and serving
  a deleted row to the builder, the solver or a new learner's copy (the enrolment copy keys schemas
  by question, so a live schema under a dead question raises there).
- **Rule:** deleting a section, question or answer option from the builder goes through **one
  `soft_delete` function**: it stamps the whole group's `deleted_at` with one `update()`, then calls
  `renumber_questions`, then resequences the live options. No builder path calls `.delete()`, except
  these hard deletes, which stay: the options a question-type change replaces
  (`surveys/models/question.py:80,85,102`), the seeded options `copy_question` replaces
  inside its own transaction, and `delete_survey` (Deferred).

  Each model's **default manager returns live rows only**; `AnswerSchema`'s returns rows whose
  question is live. So `objects` and every related manager (`survey.sections`, `section.questions`,
  `schema.options`) exclude deleted rows with no filter at the call site. The filtering manager is
  never named `base_manager_name`: forward foreign-key access and the delete collector keep seeing
  every row, so a forward read that decides membership, rendering or copying (`section_for`, a
  question's `section`) checks `deleted_at` explicitly. GraphQL must not bypass it:
  `DjangoOptimizerExtension` prefetches through `_base_manager` unless
  `prefetch_custom_queryset=True` (`surveys/schemas/schema.py:12` sets it, or each type defines
  `get_queryset`). Signals that re-read a row read it by pk through `all_objects`. An explicit
  `all_objects` manager is the only way to see deleted rows; the Django admin uses it for support.

  `AnswerSchemaOption` gains `deleted_at` by a schema migration. Rows already soft-deleted before
  this release get their children stamped by a `forms:AD-14` report-then-apply data migration that
  ships **before** the managers switch. Deletion cascades by timestamp: a deleted section stamps its
  questions and their options with the **same** `deleted_at`; a deleted question stamps its options.
  Deleted rows keep their stale `order` and are never renumbered. Learner snapshots are untouched:
  they reference template rows by plain id, not foreign key.

  There is no restore UI. A support restore clears one timestamp group under the survey lock
  (`forms:AD-25`): restored rows get `order = null` and are placed by `forms:AD-24` after their old
  neighbour; a restored `go_to` whose target is still deleted becomes `fall_through`; a question
  whose section is still deleted comes back sectionless; then `renumber_questions` and
  `assert_forward_only` (`forms:AD-5`) run.

### AD-22 — A live jump target cannot be deleted, and the refusal names who jumps there

- **Binds:** the section and question delete mutations, `forms:AD-3` edges, `clear_edges_into`
  (`surveys/signals.py:129`).
- **Prevents:** a delete silently rewriting another question's routing. Today `clear_edges_into`
  turns every `go_to` into a deleted question into `fall_through` without telling the author; that
  silent fall-through becomes a refusal. It also keeps the builder and the server from disagreeing
  about whether a delete is safe.
- **Rule:** after the survey lock (`forms:AD-25`), a delete is refused while any **live** option
  outside the set being deleted has `flow_action = go_to` and a `flow_target` inside it. The refusal
  is a named field error on `target_id` listing each referring option and its question, so the
  builder's confirmation can list them; the admin re-points them first. Edges that start inside the
  deleted set do not block — they go with it. Deleting an option never blocks: an option is an edge
  source, never a target. The legacy `Section.submit_action_target` does not block: `forms:AD-15`
  refuses writing it, and the delete nulls it.

### AD-23 — Flatten unparents an untitled section's questions in place and soft-deletes the section

- **Binds:** the flatten mutation, `move_to_section`, `forms:AD-4` placement, `forms:AD-21`,
  `media/grants.py` (was `surveys/media_access.py`).
- **Prevents:** flatten reordering anything, flatten silently discarding a heading the author
  wrote, and a question's section, schema section and option sections disagreeing after a move.
- **Rule:** flatten is allowed only on a section with no title — blank in the legacy column and in
  every translation — checked after the survey lock (`forms:AD-25`), and is refused otherwise with
  a named field error. Its questions keep their survey-wide `order` and become sectionless through
  **one `move_to_section` function**, which writes `Question.section`, `AnswerSchema.section` and
  `AnswerSchemaOption.section` together; reorder, split, flatten and copy all call it. The emptied
  section is soft-deleted by `forms:AD-21`; then `renumber_questions` runs. Contiguity holds by
  construction — the run sits between sections. No edge changes, so no `forms:AD-22` check applies.
  Media access reads a survey's questions by `survey_id`, not `section__survey_id`
  (`media/grants.py:47`, and `media/access.py`), before flatten ships, or flattened questions lose their image
  grants.

### AD-24 — Insert-after and import place by one rule, and every copy goes through one function

- **Binds:** create question, create section, duplicate question, import question,
  `duplicate_survey` (`surveys/schemas/mutations/surveys.py:247-340`).
- **Prevents:** each add path computing its own position, and the import and duplicate paths
  copying a question differently — one keeping an edge or a foreign survey's classification the
  other drops.
- **Rule:** an add from the builder names the card it follows; the target survey is that card's
  survey. A new question takes the next survey-wide position after that card and joins that card's
  section: none after a sectionless question; after a section heading it becomes that section's
  first question, and an empty section's only one. A new section placed after a question in a
  section **splits** it: the questions after that point move into the new section by
  `move_to_section` (`forms:AD-23`). A new section's auto-created first question gets an explicit
  position by the same rule. Every path runs under the survey lock (`forms:AD-25`) and ends in
  `renumber_questions` (`forms:AD-4`).

  Import copies a question from any survey in the admin's organisation they can read into the
  target survey — an **independent copy**; nothing links the two afterwards. One function,
  `copy_question`, serves duplicate and import: it copies the question, its answer schema, live
  options and all translations, resets every option's edge to `fall_through` with no target, and —
  across surveys — clears each option's `classification` and `ending_option`. [ASSUMPTION: score is
  kept; `ending_option` is cleared across surveys because `forms:AD-7` thresholds are per survey.]
  Permission is read on the source survey and update on the target. `duplicate_survey` copies live
  rows only.

### AD-25 — Every builder structure write locks the survey row first, then checks

- **Binds:** every builder write that changes edges, section membership, `order`, `deleted_at` or
  titles — delete, flatten, insert-after, split, import, reorder, translation edits — and a support
  restore.
- **Prevents:** two concurrent builder writes each passing a guard the other invalidates — a delete
  passing `forms:AD-22` while an edge into it is written, flatten passing the untitled check while a
  title is saved, two renumbers interleaving. Today `delete_question` and `delete_section` are
  neither atomic nor locked, and `translations.py` takes no lock.
- **Rule:** the write runs in one transaction and takes `select_for_update` on its `Survey` row
  before reading anything it checks; every guard (`forms:AD-5`, `forms:AD-22`, `forms:AD-23`'s
  untitled check) runs after the lock. This is the pattern the reorder and create mutations already
  use (`surveys/schemas/mutations/questions.py:150,283,319`).

### AD-26 — One image runs as three Django process roles — web, relay and consumers — with no all-in-one mode

- **Binds:** every entrypoint of `itq_forms` — the ASGI app and its lifespan, the outbox relay and
  the JetStream consumers — and the command of every Deployment built from its image.
- **Prevents:** each pod running two relays and two consumer sets, one per gunicorn worker,
  multiplied again by every web replica; a relay that releases its `SKIP LOCKED` claim before
  publishing, so two relays publish one row twice; and HTTP and queue work sharing one pod's
  limits and readiness.
- **Rule:**
  - **One image, three Django commands.** Web keeps today's command unchanged —
    `gunicorn -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --workers 2 --timeout 120
    app.asgi:application`; `--timeout 120` is the CPU-throttled boot fix and stays. Relay is
    `python manage.py relay`. Consumers is `python manage.py consume`. Both commands live in an
    app listed in `INSTALLED_APPS` — `app` is not one, so commands there are never found. All three
    run Django; Django-free workers wait for `itq_surveys`.
  - **Web runs no messaging.** Its lifespan starts no broker and no relay, and there is no
    off-switch and no all-in-one mode. This departs from `articles:AD-1`'s all-in-one default.
    Web publishes only by writing outbox rows, and `readyz` never checks NATS.
  - **The relay holds its claim — in forms' command, not the package.** `manage.py relay` drives
    unimessaging's `DjangoOutboxRelay`, which needs unimessaging 0.20.0 or later to stamp
    `Nats-Msg-Id` (`estate:AD-22`). The package runs its claim on a bare cursor, so under
    autocommit it releases the lock at once; the forms command therefore wraps each batch in
    `transaction.atomic()`, so the `SKIP LOCKED` claim holds across publish and mark
    (`estate:AD-14` clause 2). The loop is forms' own, never unimessaging's `run_standalone_relay`:
    `process_batch` calls `run_until_complete`, so it raises inside a running loop and
    `relay_loop` would still touch the heartbeat. The command creates one event loop with
    `new_event_loop` and `set_event_loop`, and each pass runs `close_old_connections()`, then
    `process_batch` synchronously inside `atomic()`. It reads `SERVICE_NAME`, `NATS_URL` and
    `OUTBOX_*` from settings — never the stock `outbox_relay` command's CLI defaults.
    `app/messaging/relay.py` is retired.
  - **Consumers bind everything, in one process.** `manage.py consume` registers every handler
    and binds every durable on the FORMS, users, orders and taxonomy brokers. Shutdown is bounded
    per step by `MESSAGING_STOP_TIMEOUT`.
  - **The relay declares FORMS; the consumers declare nothing.** `manage.py relay` creates the FORMS
    stream if absent from the contract's FORMS stream name and subjects before its first batch
    (`estate:AD-14` clause 3), and binds no durable. `manage.py consume` creates no stream; it binds
    durables only. USERS, ORDERS and TAXONOMY are never declared (`estate:AD-13`).
  - **Each role has its own health, and a heartbeat proves work, not a live loop.** Web keeps
    `healthz` and `readyz`. The relay touches its heartbeat only after a pass that did not raise.
    The consumers touch theirs only when every one of the four brokers has ticked since the last
    touch, wired into each broker directly, never from a free-running timer. Each heartbeat path
    and max age is a setting, and the max age exceeds the longest healthy pass: a full batch of
    publishes for the relay, one capped handler call for the consumers. Both are checked by
    `unimessaging.outbox.healthcheck`. The worker Deployments do not use the image's
    `curl :8000/healthz` HEALTHCHECK, since they open no port.
  - **Replicas.** Web scales freely, and the relay runs one or two. Consumers run exactly one —
    and roll by recreate, so no deploy surges a second — until the server's stored config shows
    bounded `max_deliver` for every durable (`estate:AD-22`, unimessaging 0.21.0) and every
    projection has its `estate:AD-15` replay disposition, as `articles:AD-1` gates it. This is the
    consumers' declared gap under `estate:AD-14` clause 1; those two conditions are its exit gate.
  - **Every release moves all three roles to one tag.** Relay and consumers roll first and web only
    once both are ready, so no role runs a tag the schema has moved past and web never removes the
    last consumer while a refused durable update is still failing boot.
  - **Limits ship first.** The unimessaging 0.21.0 pin and every durable's `estate:AD-22` limits go
    out in an earlier release on today's all-in-one shape. The split ships only on a later tag, so
    its rollback lands on a tag whose client already stops at the server's `max_deliver`.
  - **Cutover.** There is no all-in-one fallback, so the release is pushed only once cluster
    operations has the relay and consumer Deployments ready for the new tag. The gap until they
    start delays events and loses none, because the outbox and the durables hold them. Rollback is
    the previous tag in order: web first at one replica, then the two Deployments removed. The Deployments come from a handoff stating
    outcomes only (`estate:AD-20`), and the owner's approval is recorded in it before anyone acts.

## Consistency Conventions

| Concern | Convention |
| --- | --- |
| Naming | Authored models are bare (`Question`); the learner's copy is `User`-prefixed (`UserQuestion`). A flow column carries the same name on both. |
| Ordering | `order` is 1-based and contiguous. `forms:AD-4` changes the **question** scope from `section_id` to `survey_id`; `Section.order` is derived from each section's first question. |
| Transport | A call that does not exist today is REST; existing calls, listings and the builder screen's calls stay GraphQL (`forms:AD-20`). |
| Deletion | Builder deletes set `deleted_at` through `soft_delete`; the default manager hides them; `all_objects` is for support only (`forms:AD-21`). |
| Concurrency | A builder structure write locks the `Survey` row, then checks (`forms:AD-25`). |
| Errors | A refused flow edit returns a named field error on the offending input field, never a bare failure — the author must be told which edge or reorder was rejected and why. |
| Enum storage | A flow action is a stored string enum with an explicit default, matching how `submit_action` and `display_option` are already stored. |
| Migrations | Schema and data migrations are separate migrations in separate releases (`forms:AD-14`). |

## Stack

Seed, verified against `requirements.txt` and the Dockerfile at authoring; the code owns this
once it exists.

| Name | Version |
| --- | --- |
| Python | 3.13 |
| Django | 6.0 |
| strawberry-graphql-django | 0.70.1 |
| strawberry-graphql | unpinned here, arriving transitively. Every sibling backend pins `0.285.0` explicitly; `itq_forms` is the exception. |
| graphql-core | 3.2.12 (a bare pin; the estate-wide reason — 3.3.0 breaks strawberry at import — is recorded nowhere in this repo) |
| psycopg2-binary | 2.9.11 |
| unimessaging | 0.19.0 |
| PostgreSQL | shared schema, owned by this service's migrations |

## Structural Seed

The flow shape. Names and relationships only — an attribute that is itself an invariant is an
`AD` above, not a line here. `Question.section` and `AnswerSchemaOption.question` are
`on_delete=CASCADE`, which is what `forms:AD-9` and `forms:AD-21` turn on; `AnswerSchema.section`
and `AnswerSchemaOption.section` are nullable `SET_NULL`.

```mermaid
erDiagram
  Survey ||--o{ Section : "groups (optional)"
  Survey ||--o{ Question : "orders survey-wide"
  Section ||--o{ Question : "may group"
  Question ||--|| AnswerSchema : has
  AnswerSchema ||--o{ AnswerSchemaOption : has
  AnswerSchemaOption }o--o| Question : "flow_target when flow_action is go_to"
  UserSurvey ||--o{ UserQuestion : "snapshot, on_path recalculated"
  UserQuestion ||--|| UserAnswerSchema : has
  UserAnswerSchema ||--o{ UserAnswerOption : has
  UserAnswerOption }o--o| UserQuestion : "flow_target, remapped at enrolment"
```

The evaluation path, which `forms:AD-6` places entirely on the server:

```mermaid
sequenceDiagram
  participant S as Solver (lyr-surveys)
  participant A as answerQuestion (GraphQL)
  participant W as Path walk (one function)
  participant D as Learner snapshot
  S->>A: answer for question N
  A->>D: write answer
  A->>W: walk from the first question
  W->>D: read answers, flow_action, flow_target, snapshot order
  W->>D: recalculate on_path downstream of N
  alt path ends after N (terminate or off the end)
    W->>D: prune off-path answers
    W-->>A: ended, routing_terminate or fallthrough_complete
  else
    W-->>A: next on-path question after N
  end
  A-->>S: next question, or ended with a reason
```

## Capability → Architecture Map

| Area | Lives in | Governed by |
| --- | --- | --- |
| Edge storage and the enrolment copy | `surveys/models/answer_schema_option.py`, `user_surveys/services.py` | `forms:AD-3`, `forms:AD-2` |
| Survey-wide ordering and its backfill | `surveys/models/question.py`, `renumber_questions`, a data migration | `forms:AD-4`, `forms:AD-14` |
| Forward-only validation | `assert_forward_only`, called from `surveys/inputs.py` and the reorder path in `surveys/schemas/mutations/questions.py` | `forms:AD-5` |
| Next-question resolution and the advance result type | `user_surveys/schemas/mutations/answer_question.py` | `forms:AD-6`, `forms:AD-8`, `forms:AD-17` |
| Current path, go-back and submit pruning | the path walk, called from the answer write and submit | `forms:AD-19`, `forms:AD-17` |
| Flat solve payload | the solver's existing GraphQL load, changed in place | `forms:AD-18`, `forms:AD-20` |
| Termination | `answer_question.py`, `user_surveys/schemas/queries/should_terminate.py` | `forms:AD-7` |
| Optional sections, the `is_hidden` retirement and its carve-outs | `surveys/models/`, `user_surveys/pdf_service.py:101-104`, a data migration | `forms:AD-9`, `forms:AD-14` |
| Scoring under branching | the scoring and PDF paths | `forms:AD-10`, `forms:AD-17` |
| Shuffle interaction | `user_surveys/services.py:323-334` | `forms:AD-12` |
| Required validation and result inclusion | `user_surveys/services.py:448,520` | `forms:AD-13` |
| Soft delete, the jump-target guard and flatten | the default managers in `surveys/models/`, `soft_delete`, `move_to_section`, the delete mutations in `surveys/schemas/mutations/` | `forms:AD-21`, `forms:AD-22`, `forms:AD-23`, `forms:AD-25` |
| Insert-after, duplicate and import | `copy_question`, the create mutations, `duplicate_survey`, `renumber_questions` | `forms:AD-24`, `forms:AD-4`, `forms:AD-25` |
| Solver sequencing | `lyr-surveys` `BySection.vue:54` — `currentSectionIndex.value++`, the single sequencing point — `ByQuestion.vue`'s previous navigation, and the dead `useSolveSteps.ts:104-122` | `forms:AD-6` (consumer contract), `forms:AD-9`, `forms:AD-18`, `forms:AD-19` |
| Process roles: web, relay and consumers | `app/asgi.py`, the `relay` and `consume` management commands (in an `INSTALLED_APPS` app), `app/messaging/runtime.py`, `app/messaging_contract.py`, `Dockerfile` | `forms:AD-26` |

## Deferred

- **The `itq_surveys` follow-ups — waiting on that service's build**, which is deferred until
  `itq_forms` is finished. The ordering scope itself is closed: `estate:AD-19`, enacted in
  `surveys:AD-9` and `surveys:AD-17` (`backend` `ed147dd`). Still open, and waiting on that build:
  the three carve-outs `estate:AD-19` left undecided — the cutover ordering of the backfill
  relative to `itq_surveys`' first question mutation, which writer wins when one survey is
  renumbered under both scopes in sequence under `surveys:AD-7` and `surveys:AD-11`, and the
  `itq_surveys` owner's own review — plus `forms:AD-12`'s anchor shuffle and `forms:AD-19`'s
  pruning there. **`forms:AD-4`'s section placement** (the contiguity refusal and the derived
  `Section.order`) changes the persisted rows `itq_surveys` must reproduce under `surveys:AD-2`, so
  it is an estate call under `estate:AD-2`, as the scope was: it needs an amendment to
  `estate:AD-19` before the `itq_surveys` build, and is not settled by this spine alone.
  Likewise **soft delete, flatten and insert-after/import** (`forms:AD-21`, `forms:AD-23`,
  `forms:AD-24`) change the rows `itq_surveys` reads and writes under `surveys:AD-2` and
  `surveys:AD-13`; that is an estate call under `estate:AD-2` before the `itq_surveys` build.
- **REST estate-wide.** `forms:AD-20` binds this service only. The owner's rule that new calls
  are REST while existing calls and listings stay GraphQL across the estate is an estate call under `estate:AD-2`, to be
  written as an estate `AD`; until then no sibling service is bound by `forms:AD-20`.
- **Survey deletion stays hard.** `delete_survey` still calls `.delete()` and publishes `SurveyDeleted`; `forms:AD-21` covers the builder's section, question and option deletes only.
- **Shared asset ids on import.** `copy_question` copies a question's image reference, not the
  file; whether a copy may keep pointing at another survey's asset is open. Revisit before import ships.
- **A restore UI.** Ruled out 2026-10-12; restore is a support job over `all_objects`. Revisit if support restores become routine.
- **A REST framework dependency** (django-ninja, DRF). Not adopted; ask first.
- **An empty section's display.** `forms:AD-4` orders an empty section after all placed ones and
  the solver renders nothing for it; where the builder shows it belongs to the canvas spec.
- **What a routing terminate emits.** `SurveyResponseSubmitted` (`user_surveys/events.py`) fires
  on any submission, carries `score`, and is consumed by `itq_courses` for quiz-lesson progress.
  `forms:AD-7` creates a new terminal path and `forms:AD-10` changes what `score` means; whether
  the new path funnels through `finish_assessment`, and what `score` carries under a non-`all`
  basis, is for the story that builds it to settle with that consumer. Named here so it is not
  settled silently.
- **The authoring canvas.** How an author draws a flow belongs to the sibling builder-canvas spec
  (`.bmad-output/specs/spec-surveys-builder-canvas/`), whose `CAP-9` already rules the jump
  refusal `forms:AD-15` implements; this spine stays consistent with it and does not restate it.
- **Dropping `submit_action` / `submit_action_target`.** Deferred by `forms:AD-15` to a release
  not already carrying two learner-data migrations.
- **Multi-condition edges** ("if A and B"). `forms:AD-3` hangs one edge off one option, so a
  conjunction is not expressible. Revisit only on a real authoring need, as a new decision.
- **The (A)-versus-(B) shape.** The comparable-platform research concluded for
  conditions-on-elements (B); the product owner overruled for question-level edges (A), which is
  what this spine builds. (A)'s documented failure modes — order-dependence under randomisation,
  no way to hide one question without an edge — are answered by `forms:AD-12` and `forms:AD-9`.
  The ruling is closed; recorded so a later reader does not reopen it as an oversight.
- **A scored variant of the acceptance fixture.** The seeded "Section Jump Navigation" survey is
  `is_evaluable=False`, so it cannot demonstrate `forms:AD-10`. The story proving score basis needs
  a scored fixture.
- **The operational envelope** — deployment, environments, replicas, provider topology. Owned by
  the estate and the deploy pipeline; `estate:AD-14` is the only part reaching into this scope.
- **The rest of `itq_forms`.** This is an epic-altitude spine covering the flow engine.
  Classifications, recommendations, translations, pricing and messaging are not ruled here and
  keep whatever conventions their code already shows.
- **The rest of the service's invariants.** Beyond `forms:AD-1` and the flow engine, the gaps
  this repo knows it owes are recorded here as they are noticed — a named gap is worth more than
  silence, because it stops the next reader concluding the question was never asked.
- **More than one consumer replica** — waits until every durable carries `estate:AD-22` limits
  under `forms:AD-26`; revisit when that epic ships.
- **Django-free relay and consumers** — wait for the `itq_surveys` FastAPI move, which has no
  brief yet.

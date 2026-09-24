-- How much room is left in the `User*.origin_id` snapshot pointers, and what
-- widening them would cost. Read-only: every statement here is a SELECT.
--
--   psql "$FORMS_DATABASE_URL" -f tools/audit_snapshot_origin_id_headroom.sql
--
-- ── The ruling this measures (2026-09-24) ────────────────────────────────
--
-- All eight `user_surveys.User*.origin_id` columns are `IntegerField` (int4)
-- while every source primary key they point at is `BigAutoField` (int8). The
-- pointer is narrower than what it points at. Asked whether to widen them:
-- **no, not now** — and if ever, all eight together, in a scheduled window.
-- Recorded rather than left silent, because the next reader will notice the
-- mismatch and deserves to find the question already asked.
--
-- 1. Widening the column does not lift the ceiling. `origin_id` is exposed as
--    GraphQL `Int` (`user_surveys/types/user_survey.py:145` and the seven
--    siblings below it, each `origin_id: auto`), and the GraphQL spec fixes
--    `Int` at signed 32 bits. strawberry-django maps `BigIntegerField` to
--    plain `int` exactly as it maps `IntegerField`
--    (`strawberry_django/fields/types.py:237`), so a widened column still
--    serialises through a 32-bit scalar. Widening alone would move the
--    failure from a refused INSERT at enrolment — loud, before any row
--    exists — to a serialisation error when a learner opens their result.
--    That is strictly worse. Lifting the ceiling for real means the column,
--    a `BigInt` scalar, and every generated client type; that is a different
--    piece of work from the one this story asked about.
--
-- 2. What consumes the ceiling is authoring, not traffic. Every one of the
--    eight points at an admin-authored row — sections, questions, answer
--    schemas, options, classifications, recommendations, score bands and
--    their pinned materials. The per-learner tables are the `user_surveys_*`
--    ones, and their own primary keys are already int8. So the sequence that
--    would have to reach 2,147,483,647 advances when someone builds a survey,
--    not when someone takes one.
--
-- 3. The cost argument cuts both ways, which is why it is measured here and
--    not asserted. `ALTER COLUMN TYPE bigint` rewrites the table and rebuilds
--    the index (all eight are `db_index=True`) under ACCESS EXCLUSIVE, and it
--    is the *snapshot* tables that would be rewritten — the ones that grow
--    with every enrolment. "Do it now while it is cheap" is a claim about a
--    size this repository cannot read. Query B reads it.
--
-- ── What reverses this ────────────────────────────────────────────────────
--
-- Any source sequence in query A above 1% of the int4 ceiling (21,474,836).
-- That is four orders of magnitude of warning at today's authoring rate and
-- still leaves the rewrite ahead of the numbers, not behind them. At that
-- point widen all eight columns in one migration, together with the GraphQL
-- scalar — point 1 — and run it in a maintenance window, not as a deploy
-- migration.
--
-- ── Unverified ────────────────────────────────────────────────────────────
--
-- Nothing here has been run. The ruling rests on points 1 and 2, which are
-- checkable in the checkout; point 3 is the part that needs this file run
-- against production, and it was not available when the ruling was made.

\echo '== A. headroom: how close each source sequence is to the int4 ceiling =='
-- `max(id)`, not the sequence's `last_value`: a deleted row still consumed its
-- number, so the sequence is the honest measure of what has been spent — but
-- it is per-table and not always named predictably, and max(id) tracks it
-- closely enough to answer "which order of magnitude are we in". Expect every
-- row well under 0.01%.
          SELECT 'surveys_section' AS source_table, max(id) AS max_id,
                 round(100.0 * max(id) / 2147483647, 6) AS pct_of_int4 FROM surveys_section
UNION ALL SELECT 'surveys_question',              max(id), round(100.0 * max(id) / 2147483647, 6) FROM surveys_question
UNION ALL SELECT 'surveys_answerschema',          max(id), round(100.0 * max(id) / 2147483647, 6) FROM surveys_answerschema
UNION ALL SELECT 'surveys_answerschemaoption',    max(id), round(100.0 * max(id) / 2147483647, 6) FROM surveys_answerschemaoption
UNION ALL SELECT 'classifications_classification',max(id), round(100.0 * max(id) / 2147483647, 6) FROM classifications_classification
UNION ALL SELECT 'recommendations_recommendation',max(id), round(100.0 * max(id) / 2147483647, 6) FROM recommendations_recommendation
UNION ALL SELECT 'recommendations_action',        max(id), round(100.0 * max(id) / 2147483647, 6) FROM recommendations_action
UNION ALL SELECT 'recommendations_material',      max(id), round(100.0 * max(id) / 2147483647, 6) FROM recommendations_material
ORDER BY pct_of_int4 DESC NULLS LAST;

\echo '== B. rewrite cost: the snapshot tables an ALTER TYPE would rewrite =='
-- `reltuples` is the planner's estimate, not a count — a `count(*)` over the
-- per-enrolment tables is itself the kind of scan this file exists to avoid.
-- Size includes indexes and TOAST, which is what the rewrite actually moves.
SELECT
    c.relname AS snapshot_table,
    CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END AS est_rows,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
    pg_total_relation_size(c.oid) AS total_bytes
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = current_schema()
  AND c.relname IN (
      'user_surveys_usersection',
      'user_surveys_userquestion',
      'user_surveys_useranswerschema',
      'user_surveys_useransweroption',
      'user_surveys_userclassification',
      'user_surveys_userrecommendation',
      'user_surveys_useraction',
      'user_surveys_usermaterial'
  )
ORDER BY total_bytes DESC;

\echo '== C. confirmation that the mismatch is still what it was =='
-- If any of these reads `bigint`, part of the widening has already happened
-- and the ruling above is describing a state that no longer exists.
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND column_name = 'origin_id'
  AND table_name LIKE 'user_surveys_%'
ORDER BY table_name;

-- What `Survey.primary_language` holds, and a check that the backfill was right.
-- Read-only: every statement here is a SELECT. `forms:AD-1`.
--
--   psql "$FORMS_DATABASE_URL" -f tools/audit_primary_locale.sql
--
-- This is NOT a prerequisite for the migration. `surveys/0041` backfills the
-- new column with the value the old code already chose, so no survey's primary
-- locale moves as it lands and nothing here has to be checked first. Query A
-- states that selector in SQL — it is the written-down definition of what got
-- written — and query C re-runs it against the column afterwards.
--
-- Before the migration, "the survey's primary locale" was spelled three times
-- in Python, always as `survey.translations.first()`. Django resolves `first()`
-- on an unordered queryset as `ORDER BY pk`, so all three meant the language of
-- the lowest-id translation row: stable for a fixed set of rows, but naming a
-- language nobody chose, and a different one per survey. That is what A
-- reproduces.

\echo '== A. what the backfill writes: the old selector, per survey =='
-- The language of each survey's lowest-id translation row. Surveys with no
-- translations come back NULL and keep a null column; they read as
-- `Survey.PRIMARY_LANGUAGE_FALLBACK` ("default"), which is what the enrolment
-- snapshot has always done for them.
SELECT
    coalesce(
        (SELECT t.language FROM surveys_surveytranslation t
          WHERE t.survey_id = s.id ORDER BY t.id LIMIT 1),
        '(none — stays null)'
    ) AS backfilled_primary,
    count(*) AS surveys
FROM surveys_survey s
GROUP BY 1
ORDER BY surveys DESC;

\echo '== B. surveys where the stored primary has no translation behind it =='
-- Not a defect the migration introduces — the old code had the same shape —
-- but worth seeing. A survey whose primary language has no translation row
-- serves `Survey.title` as NULL, and the snapshot files every legacy column
-- under a language the survey is not authored in. Expect zero while the column
-- is only ever set from an existing translation; a hand-edited primary or a
-- deleted translation row can produce one.
SELECT s.id, s.status, s.primary_language
FROM surveys_survey s
WHERE s.primary_language IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM surveys_surveytranslation t
       WHERE t.survey_id = s.id AND t.language = s.primary_language
  )
ORDER BY s.id;

\echo '== C. post-migration check: stored value vs the old selector =='
-- Run after 0041. Every row here is a survey whose primary locale moved as the
-- migration landed, which the backfill is built not to do. An empty result is
-- the proof that the change was behaviour-preserving on this data; anything
-- else means the backfill did not run, ran against a moving target, or someone
-- has since edited the column by hand.
SELECT
    s.id,
    s.primary_language AS stored,
    (SELECT t.language FROM surveys_surveytranslation t
      WHERE t.survey_id = s.id ORDER BY t.id LIMIT 1) AS old_selector
FROM surveys_survey s
WHERE s.primary_language IS DISTINCT FROM (
        SELECT t.language FROM surveys_surveytranslation t
         WHERE t.survey_id = s.id ORDER BY t.id LIMIT 1
      )
ORDER BY s.id;

-- ── D/E: what 0044 moves to `ar`, and what it leaves ─────────────────
-- Ruled 2026-09-29 (`forms:AD-1`): every survey no learner has enrolled in
-- moves to `ar`; a survey with any `UserSurvey` keeps its primary, because
-- each enrolment froze it into that learner's snapshot. Run this before the
-- release to record the counts, and again after it: D should then be empty,
-- and E unchanged.
--
-- `languages` is every translation language; `titled` those with a title. A
-- survey in D with no `ar` in `titled` reads `Survey.title` as NULL once it
-- moves — the accepted cost of moving all of them.

\echo '== D. unenrolled surveys not on `ar`: 0044 moves these =='
SELECT
    s.id,
    s.status,
    s.created_at,
    s.primary_language,
    string_agg(t.language, ',' ORDER BY t.language) AS languages,
    string_agg(t.language, ',' ORDER BY t.language)
        FILTER (WHERE nullif(btrim(t.title), '') IS NOT NULL) AS titled
FROM surveys_survey s
LEFT JOIN surveys_surveytranslation t ON t.survey_id = s.id
WHERE s.primary_language IS DISTINCT FROM 'ar'
  AND NOT EXISTS (SELECT 1 FROM user_surveys_usersurvey us WHERE us.survey_id = s.id)
GROUP BY s.id, s.status, s.created_at, s.primary_language
ORDER BY s.id;

\echo '== E. enrolled surveys not on `ar`: 0044 leaves these, each needs a ruling =='
SELECT
    s.id,
    s.status,
    s.created_at,
    s.primary_language,
    (SELECT string_agg(t.language, ',' ORDER BY t.language)
       FROM surveys_surveytranslation t WHERE t.survey_id = s.id) AS languages,
    (SELECT count(*) FROM user_surveys_usersurvey us WHERE us.survey_id = s.id) AS enrolments
FROM surveys_survey s
WHERE s.primary_language IS DISTINCT FROM 'ar'
  AND EXISTS (SELECT 1 FROM user_surveys_usersurvey us WHERE us.survey_id = s.id)
ORDER BY s.id;

\echo '== F. counts =='
SELECT
    CASE WHEN EXISTS (SELECT 1 FROM user_surveys_usersurvey us WHERE us.survey_id = s.id)
         THEN 'enrolled — stays' ELSE 'not enrolled — moves' END AS split,
    coalesce(s.primary_language, '(null)') AS primary_language,
    count(*) AS surveys,
    count(*) FILTER (WHERE s.status = 'published') AS published
FROM surveys_survey s
WHERE s.primary_language IS DISTINCT FROM 'ar'
GROUP BY 1, 2
ORDER BY 1, 2;

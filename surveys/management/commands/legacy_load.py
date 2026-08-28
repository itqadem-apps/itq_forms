"""Load the legacy `assessments` app into itq_forms, reconciling in place.

Reconcile in place, not truncate-and-reload: the target already carries real
work that references importer-created rows -- 50 user attempts across 12
imported surveys, 580 pricing rows, one usage row. Deleting the imported rows
to reload them cleanly would take those with them.

Every row therefore goes through `migration_spec.resolve`, which decides from a
witness -- not from the id -- whether a legacy row is already present. Read that
module before changing anything here.

ONE-SHOT, BY DESIGN
-------------------
`--apply` may be run exactly once against a given target; the second attempt is
refused. This is not a limitation waiting to be fixed, it is the chosen design,
and the retry path is `restore the target from backup and run again`.

The reason is that a remapped row cannot recognise itself on a second run. When
a legacy id is already taken, the row is written under a fresh id, and the
witness for schemas, options and actions is the *parent chain*. After a remap
the legacy chain (survey 2, section 229, question 3079) and the target chain
(survey 2, section 240, question 3079) no longer agree, so run two reads its own
output as somebody else's row and writes a duplicate. Making that work means
persisting the id map as durable state and resolving every chain through it --
real machinery, existing only to serve a scenario a restore already covers.

The same maintenance window that makes restore-and-retry cheap also closes the
allocator race: _allocator hands out explicit ids that, on five of nine tables,
are exactly the ids the live sequence would hand a concurrent INSERT. So --apply
takes an EXCLUSIVE lock on every table it writes, and the app must be quiesced.

Dry run by default and genuinely read-only: the transaction is rolled back, the
sequences are only reported (setval is NOT transactional, so it must not run
until the load has committed), and every id is explicit so no nextval is burned.

    manage.py legacy_load --legacy-dsn "postgresql://.../legacy"
    manage.py legacy_load --legacy-dsn "..." --organization-id <uuid> \\
        --apply --backup-confirmed
"""

import json
from collections import defaultdict
from uuid import uuid4

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from surveys.migration_spec.resolve import Mode, _ms, resolve, resolve_by_witness
from surveys.migration_spec.spec import (
    TABLES,
    assert_target_total,
    assert_total,
    map_collection_status,
    map_display_option,
    map_sponsor,
    map_submit_action,
    map_survey_type,
)

DEFAULT_LANGUAGE = "ar"

# Written on --apply, checked on every run. This load is deliberately one-shot:
# see _guard_single_run().
RUN_MARKER = "migration_legacy_load_run"


class DryRun(Exception):
    """Raised to roll a dry run back. Never escapes handle()."""


class Command(BaseCommand):
    help = "Load the legacy assessments app into itq_forms. Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--legacy-dsn", required=True)
        parser.add_argument("--apply", action="store_true",
                            help="commit. Without it the transaction is rolled back.")
        parser.add_argument("--organization-id", default=None,
                            help="organization every inserted survey and collection belongs to. "
                                 "Required with --apply: it is the key that gates all event "
                                 "publishing, and a row without it can never reach NATS.")
        parser.add_argument("--backup-confirmed", action="store_true",
                            help="assert a restorable backup of the target exists. Required with "
                                 "--apply, because restore is this load's only retry path.")
        parser.add_argument("--id-map", default=None,
                            help="write the legacy_id -> target_id map here as JSON")

    # -- entry point ---------------------------------------------------------

    def handle(self, *args, **opts):
        import psycopg

        self.apply = opts["apply"]
        self.org_id = opts["organization_id"]
        self.maps = {}
        self.modes = {}
        self._high = {}
        self.expected = defaultdict(dict)   # target table -> {pk: {column: value}}
        self.seq_plan = []

        if self.apply:
            if not opts["backup_confirmed"]:
                raise SystemExit(
                    "--apply requires --backup-confirmed.\n\n"
                    "This load is one-shot: it cannot be run twice against the same target, so a "
                    "restorable backup is the only way back from a bad run. Take one, verify you "
                    "can restore it, then pass --backup-confirmed.")
            if not self.org_id:
                raise SystemExit(
                    "--apply requires --organization-id.\n\n"
                    "Every survey and collection this load inserts needs one. It is nullable in "
                    "the schema, so the database will not stop you -- but surveys/messaging.py "
                    "skips publishing any row whose organization_id is null, permanently and "
                    "silently. Pass the organization these surveys belong to.")
            self._check_uuid(self.org_id)

        with psycopg.connect(opts["legacy_dsn"]) as src:
            self.src = src
            self._check_coverage()
            self._check_lengths()
            try:
                with transaction.atomic():
                    with connection.cursor() as cur:
                        self.cur = cur
                        self._guard_single_run()
                        self._lock_targets()
                        self._check_target_coverage()
                        self._check_organization()
                        self._resolve_all()
                        self._load()
                        self._prune_stale()
                        self._plan_sequences()
                        self._verify()
                        self._stamp_run()
                    if not self.apply:
                        raise DryRun
            except DryRun:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING(
                    "DRY RUN -- rolled back, and nothing outside the transaction was touched "
                    "either: the sequences above were reported, not set."))
            else:
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS("committed"))
                # setval() is not transactional, so it cannot run until now: inside
                # the transaction it would survive a rollback and leave a dry run
                # having permanently moved production sequences.
                self._apply_sequences()

        # Only meaningful once the ids in it actually exist. On a dry run the
        # minted category UUIDs were rolled back and would never be seen again.
        if opts["id_map"]:
            if self.apply:
                self._write_id_map(opts["id_map"])
            else:
                self.stdout.write(self.style.WARNING(
                    f"--id-map not written: this was a dry run, so the ids in it -- including "
                    f"freshly minted category UUIDs -- were rolled back and would describe "
                    f"nothing that exists."))

    @staticmethod
    def _check_uuid(value):
        from uuid import UUID
        try:
            UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            raise SystemExit(f"--organization-id {value!r} is not a UUID")

    # -- helpers -------------------------------------------------------------

    def q(self, sql, params=None):
        return self.src.execute(sql, params).fetchall()

    def t(self, sql, params=None):
        self.cur.execute(sql, params)
        return self.cur.fetchall() if self.cur.description else None

    def say(self, msg):
        self.stdout.write(msg)

    def _check_coverage(self):
        cols = defaultdict(set)
        for tbl, col in self.q("select table_name, column_name from information_schema.columns "
                               "where table_schema='public'"):
            cols[tbl].add(col)
        assert_total(cols)
        self.say(self.style.SUCCESS(
            f"mapping is total over {len(TABLES)} tables / "
            f"{sum(len(t.columns) for t in TABLES)} columns"))

    # -- gates ---------------------------------------------------------------

    def _guard_single_run(self):
        """Refuse a second --apply. See the module docstring for why.

        The marker lives in the target, so restoring the target from backup
        clears it -- which is exactly the intended retry path, and the reason
        this needs no --force escape hatch. An escape hatch would only ever be
        used in the situation the guard exists to prevent.
        """
        self.cur.execute(
            f"create table if not exists {RUN_MARKER} ("
            f"  id serial primary key,"
            f"  applied_at timestamptz not null default now(),"
            f"  legacy_rows jsonb)")
        prior = self.t(f"select applied_at from {RUN_MARKER} order by applied_at")
        if prior:
            when = ", ".join(str(r[0]) for r in prior)
            raise SystemExit(
                f"this target has already been loaded ({when}).\n\n"
                f"The load is one-shot: a row it remapped cannot recognise itself on a "
                f"second run, so re-running duplicates rows rather than refreshing them.\n"
                f"To retry: restore the target from the backup taken before the first run "
                f"and run again. That clears this marker with it.")
        self.say(self.style.SUCCESS("no prior load on this target"))

    LOCKED = [
        "surveys_survey", "surveys_section", "surveys_question",
        "surveys_answerschema", "surveys_answerschemaoption",
        "classifications_classification", "recommendations_action",
        "recommendations_recommendation", "survey_collections_surveycollection",
        "survey_collections_surveycollection_assessments", "taxonomy_category",
    ]

    def _lock_targets(self):
        """Stop concurrent writers for the duration of the load.

        _allocator hands out explicit ids computed from max(id). On five of the
        nine allocated tables the first id it hands out is byte-identical to the
        next value the live sequence would give an ordinary Django INSERT, so an
        application write landing mid-load either loses its row to a duplicate
        key or takes an id this load is about to claim. EXCLUSIVE blocks writers
        and still allows SELECT, so reads keep serving while this runs.

        A dry run takes no locks: it writes nothing, and locking production
        tables to preview a migration would be its own outage.
        """
        if not self.apply:
            self.say("dry run: no locks taken")
            return
        for table in self.LOCKED:
            self.cur.execute(f"lock table {table} in exclusive mode")
        self.say(self.style.SUCCESS(f"exclusive lock held on {len(self.LOCKED)} target tables"))

    def _written_columns(self):
        """Every target column this load supplies, by table."""
        return {
            "surveys_survey": set(self.SURVEY_COLS) | set(self.SURVEY_INSERT_ONLY)
                              | {"organization_id"},
            "surveys_section": set(self.SECTION_COLS) | {"submit_action_target_id"},
            "surveys_question": set(self.QUESTION_COLS),
            "surveys_answerschema": set(self.SCHEMA_COLS),
            "surveys_answerschemaoption": set(self.OPTION_COLS),
            "classifications_classification": {
                "id", "survey_id", "score", "created_at", "updated_at", "deleted_at"},
            "recommendations_action": {"id", "survey_id", "upper_limit", "lower_limit"},
            "recommendations_recommendation": {
                "id", "survey_id", "option_id", "created_at", "updated_at", "deleted_at"},
            "survey_collections_surveycollection": set(self.COLLECTION_COLS) | {"organization_id"},
            "taxonomy_category": {"category_id", "tree_id", "name", "path_text"},
        }

    def _check_target_coverage(self):
        """The other half of assert_total: rule on every column of the target.

        assert_total walks the legacy catalog, so it is structurally blind to a
        target column with no legacy source. organization_id is exactly that,
        and it went unwritten on every inserted row.
        """
        cols = defaultdict(set)
        for tbl, col in self.t(
                "select table_name, column_name from information_schema.columns "
                "where table_schema='public'"):
            cols[tbl].add(col)
        assert_target_total(cols, self._written_columns())
        self.say(self.style.SUCCESS("every column of every written target table is ruled on"))

    def _check_organization(self):
        """A dry run without --organization-id still has to say what it would do."""
        if self.org_id is None:
            self.say(self.style.WARNING(
                "no --organization-id: inserted rows would get NULL and could never be "
                "published. Required for --apply."))
            return
        known = self.t(
            "select count(*) from ("
            "  select organization_id from surveys_survey"
            "  union select organization_id from survey_collections_surveycollection) o "
            "where organization_id = %s", (self.org_id,))[0][0]
        if not known:
            self.say(self.style.WARNING(
                f"organization {self.org_id} owns no existing survey or collection on this "
                f"target. Not fatal -- a first load for a new organization looks like this -- "
                f"but check the id if you expected otherwise."))
        else:
            self.say(self.style.SUCCESS(f"organization {self.org_id} is known to this target"))

    def _stamp_run(self):
        """Record the run so the guard can refuse the next one."""
        if not self.apply:
            return
        counts = {t: len(m) for t, m in self.maps.items()}
        self.cur.execute(
            f"insert into {RUN_MARKER} (legacy_rows) values (%s)", (json.dumps(counts),))

    # legacy expression -> the target column it lands in. The limit itself is
    # read from the target catalog, so widening a column here needs no edit.
    LENGTH_CHECKS = [
        ("assessments_assessment", "title", "surveys_surveytranslation", "title"),
        ("assessments_assessment", "short_description",
         "surveys_surveytranslation", "short_description"),
        ("assessments_section", "title", "surveys_section", "title"),
        ("assessments_question", "title", "surveys_question", "title"),
        ("assessments_classification", "name",
         "classifications_classificationtranslation", "name"),
        ("assessments_action", "title", "recommendations_actiontranslation", "title"),
        ("blogs_blog", "slug", "survey_collections_surveycollectiontranslation", "slug"),
    ]
    # blogs_blog stores these as jsonb, one value per language key.
    JSON_LENGTH_CHECKS = [
        ("title", "survey_collections_surveycollectiontranslation", "title"),
        ("description", "survey_collections_surveycollectiontranslation", "description"),
        ("short_description",
         "survey_collections_surveycollectiontranslation", "short_description"),
    ]

    def _limit(self, table, column):
        row = self.t("select character_maximum_length from information_schema.columns "
                     "where table_schema='public' and table_name=%s and column_name=%s",
                     (table, column))
        if not row:
            raise SystemExit(f"{table}.{column} does not exist on the target")
        return row[0][0]          # None for text/jsonb -- unbounded

    def _check_lengths(self):
        """Refuse the load if any legacy value is longer than the column it lands in.

        Postgres raises this mid-INSERT, thousands of rows in, naming only the
        type -- not the row, not even the table. Finding it up front costs one
        query per column and turns a stack trace into a decision.
        """
        problems = []
        with connection.cursor() as cur:
            self.cur = cur
            checks = [(lt, lc, f"{tt}.{tc}", self._limit(tt, tc))
                      for lt, lc, tt, tc in self.LENGTH_CHECKS]
            jchecks = [(lc, f"{tt}.{tc}", self._limit(tt, tc))
                       for lc, tt, tc in self.JSON_LENGTH_CHECKS]
        for table, col, target, limit in checks:
            if limit is None:
                continue
            n, longest = self.q(
                f'select count(*) filter (where length("{col}") > %s), '
                f'coalesce(max(length("{col}")), 0) from {table}', (limit,))[0]
            if n:
                problems.append(f"{table}.{col}: {n} value(s) exceed {target} "
                                f"({limit} chars); longest is {longest}")
        for col, target, limit in jchecks:
            if limit is None:
                continue
            n, longest = self.q(
                f"select count(*) filter (where length(v) > %s), coalesce(max(length(v)), 0) "
                f"from (select (jsonb_each_text({col})).value v from blogs_blog) x",
                (limit,))[0]
            if n:
                problems.append(f"blogs_blog.{col}: {n} value(s) exceed {target} "
                                f"({limit} chars); longest is {longest}")
        if problems:
            raise SystemExit("values too long for their target columns:\n  "
                             + "\n  ".join(problems)
                             + "\n\nWiden the column or agree a truncation -- this load "
                               "will not silently shorten anyone's text.")
        self.say(self.style.SUCCESS("every legacy value fits its target column"))

    def _allocator(self, table, legacy_max=0):
        """Hand out ids above everything either database currently holds.

        Above the *legacy* maximum too, not just the target's: rows that are new
        but uncontested keep their legacy id, so an allocator that only cleared
        the target's high-water mark would hand a remapped row an id an
        insert-mode row is about to claim. That is exactly what happened at
        question 3091 the first time this ran.

        Deliberately not nextval(): the recommendation sequence sits below
        max(id) in production, so nextval would return a taken id. The sequences
        are repaired at the end of the load instead.
        """
        if table not in self._high:
            target_max = self.t(f"select coalesce(max(id), 0) from {table}")[0][0]
            self._high[table] = max(target_max, legacy_max or 0)

        def nxt():
            self._high[table] += 1
            return self._high[table]

        return nxt

    # -- resolution ----------------------------------------------------------

    def _resolve_all(self):
        self.say("")
        self.say("resolving legacy rows against the target:")

        def stamped(sql_l, sql_t, name, target_table):
            lg = {i: _ms(ts) for i, ts in self.q(sql_l)}
            tg = {i: _ms(ts) for i, ts in self.t(sql_t)}
            r = resolve(name, lg, tg,
                        self._allocator(target_table, max(lg, default=0)))
            self._record(r)

        stamped("select id, created_at from assessments_assessment",
                "select id, created_at from surveys_survey",
                "survey", "surveys_survey")
        stamped("select id, created_at from assessments_section",
                "select id, created_at from surveys_section",
                "section", "surveys_section")
        stamped("select id, created_at from assessments_question",
                "select id, created_at from surveys_question",
                "question", "surveys_question")
        stamped("select id, created_at from assessments_classification",
                "select id, created_at from classifications_classification",
                "classification", "classifications_classification")
        stamped("select id, created_at from assessments_recommendation",
                "select id, created_at from recommendations_recommendation",
                "recommendation", "recommendations_recommendation")

        # No created_at on these three. The parent chain is the witness.
        def chained(sql_l, sql_t, name, target_table):
            lg = {r[0]: tuple(r[1:]) for r in self.q(sql_l)}
            tg = {r[0]: tuple(r[1:]) for r in self.t(sql_t)}
            self._record(resolve(name, lg, tg,
                                 self._allocator(target_table, max(lg, default=0))))

        chained("select id, assessment_id, section_id, question_id from assessments_answerschema",
                "select id, survey_id, section_id, question_id from surveys_answerschema",
                "schema", "surveys_answerschema")
        chained("select id, assessment_id, section_id, question_id, schema_id "
                "from assessments_answerschemaoption",
                "select id, survey_id, section_id, question_id, schema_id "
                "from surveys_answerschemaoption",
                "option", "surveys_answerschemaoption")
        chained("select id, assessment_id from assessments_action",
                "select id, survey_id from recommendations_action",
                "action", "recommendations_action")

        # Collections were renumbered by the old importer, so their ids witness
        # nothing. created_at does.
        lg = {i: _ms(ts) for i, ts in self.q("select id, created_at from blogs_blog")}
        tg = {i: _ms(ts) for i, ts in
              self.t("select id, created_at from survey_collections_surveycollection")}
        self._record(resolve_by_witness(
            "collection", lg, tg,
            self._allocator("survey_collections_surveycollection", max(lg, default=0))))

    def _record(self, r):
        self.maps[r.table] = r.mapping
        self.modes[r.table] = r.mode
        c = r.counts
        style = self.style.WARNING if c[Mode.REMAP] else (lambda s: s)
        self.say(f"  {r.table:<16}{len(r.mapping):>7} legacy  "
                 f"{c[Mode.UPDATE]:>7} update  {c[Mode.INSERT]:>6} insert  "
                 + style(f"{c[Mode.REMAP]:>4} remapped"))

    def m(self, table, legacy_id):
        """Legacy id -> target id. None passes through."""
        if legacy_id is None:
            return None
        try:
            return self.maps[table][legacy_id]
        except KeyError:
            raise SystemExit(
                f"{table} {legacy_id} is referenced but has no resolution -- "
                f"the source is not referentially closed")

    # -- writes --------------------------------------------------------------

    def _load(self):
        self.say("")
        self.say("writing:")
        self._categories()
        self._surveys()
        self._sections()
        self._questions()
        self._schemas()
        self._classifications()      # options reference classifications
        self._options()
        self._actions()
        self._recommendations()
        self._collections()
        self._section_targets()      # self-FK, needs every section to exist

    def _write(self, table, cols, insert_rows, update_rows, pk="id", insert_only=None):
        """Insert new rows and update matched ones. Inserts must not conflict.

        A conflict here would mean the resolution said a target id was free when
        it was not, which is the one failure this whole design exists to prevent
        -- so it is left to raise rather than swallowed by ON CONFLICT.

        `insert_only` is {column: value} for NOT NULL columns the legacy schema
        has no source for. They are supplied on INSERT and deliberately left
        alone on UPDATE: they belong to the new system, and a person may have
        set them on a row we are only refreshing.
        """
        insert_only = insert_only or {}
        if insert_rows:
            icols = cols + list(insert_only)
            ph = ", ".join(["%s"] * len(icols))
            names = ", ".join(f'"{c}"' for c in icols)
            extra = list(insert_only.values())
            self.cur.executemany(
                f"insert into {table} ({names}) values ({ph})",
                [list(r) + extra for r in insert_rows])
        if update_rows:
            assign = ", ".join(f'"{c}" = %s' for c in cols if c != pk)
            self.cur.executemany(
                f"update {table} set {assign} where {pk} = %s",
                [[v for c, v in zip(cols, row) if c != pk] + [dict(zip(cols, row))[pk]]
                 for row in update_rows])
        # What this load claims the target now holds. _verify() reads the rows
        # back and compares; without this it could only count rows, which is
        # why a sabotaged run that dropped every translation still passed.
        for row in list(insert_rows) + list(update_rows):
            d = dict(zip(cols, row))
            self.expected[table][d[pk]] = d
        self.say(f"  {table:<44}{len(insert_rows):>7} inserted  {len(update_rows):>7} updated")

    def _split(self, table, rows_by_legacy_id):
        ins, upd = [], []
        for lid, row in rows_by_legacy_id:
            (upd if self.modes[table][lid] is Mode.UPDATE else ins).append(row)
        return ins, upd

    def _translations(self, table, fk, cols, rows, uuid_pk=True):
        """Upsert translation rows keyed on (fk, language)."""
        if not rows:
            return
        allcols = (["id"] if uuid_pk else []) + [fk, "language"] + cols
        names = ", ".join(f'"{c}"' for c in allcols)
        ph = ", ".join(["%s"] * len(allcols))
        assign = ", ".join(f'"{c}" = excluded."{c}"' for c in cols)
        payload = [([str(uuid4())] if uuid_pk else []) + list(r) for r in rows]
        self.cur.executemany(
            f"insert into {table} ({names}) values ({ph}) "
            f"on conflict ({fk}, language) do update set {assign}",
            payload)
        # Keyed on (fk, language) rather than the pk: on conflict the pk kept is
        # the row already there, not the uuid4 minted a line above.
        for r in rows:
            self.expected[table][(r[0], r[1])] = dict(zip([fk, "language"] + cols, r))
        self.say(f"  {table:<44}{len(payload):>7} translations")

    # -- taxonomy ------------------------------------------------------------

    def _categories(self):
        """Legacy category ids are ints; the target uses UUIDs it minted itself.

        The old importer's UUIDs were random, so they cannot be recomputed --
        existing categories are matched by translated name. Slug cannot be the
        key: two legacy categories share the slug 'autism'.
        """
        existing = {}
        for cat_id, lang, name in self.t(
                "select category_id, language, name from taxonomy_categorytranslation"):
            existing[(lang, (name or "").strip())] = str(cat_id)

        legacy = self.q("select id, name, slug, tree_id, parent_id, level "
                        "from classifications_category")
        nested = [r for r in legacy if r[4] is not None or r[5]]
        if nested:
            raise SystemExit(
                f"{len(nested)} legacy categories are nested; path_text materialisation "
                f"is not implemented because every live category is a root")

        self.cat_map, cat_ins, tr_rows = {}, [], []
        self.minted_categories = set()
        for cid, name_json, slug, tree_id, _parent, _level in legacy:
            names = name_json or {}
            hit = next((existing[(l, (v or "").strip())]
                        for l, v in names.items()
                        if (l, (v or "").strip()) in existing), None)
            if hit is None:
                hit = str(uuid4())
                self.minted_categories.add(hit)
                display = names.get(DEFAULT_LANGUAGE) or next(iter(names.values()), None)
                cat_ins.append((hit, str(uuid4()), display, display))
            self.cat_map[cid] = hit
            for lang, value in names.items():
                tr_rows.append((hit, lang, value, slug))

        self._write("taxonomy_category",
                    ["category_id", "tree_id", "name", "path_text"], cat_ins, [],
                    pk="category_id")
        self._translations("taxonomy_categorytranslation", "category_id",
                           ["name", "slug"], tr_rows)

    # -- surveys -------------------------------------------------------------

    SURVEY_COLS = [
        "id", "status", "survey_type", "display_option", "is_timed", "is_for_child",
        "is_evaluable", "evaluation_type", "use_score", "use_classifications",
        "use_recommendations", "use_actions", "allow_end_based_on_answer_repeat",
        "answers_count_to_end", "end_based_on_answer_repeat_in_row",
        "allow_update_answer_options_scores_based_on_classification",
        "allow_update_answer_options_text_based_on_classification",
        "create_option_for_each_classification", "created_at", "updated_at",
        "deleted_at", "category_id", "sponsor",
    ]

    # NOT NULL on the target, no legacy source. Written on INSERT only -- see
    # _write() -- so that a person's setting on an existing row survives a reload.
    SURVEY_INSERT_ONLY = {
        "enable_anti_cheat": False,
        "lock_answers": False,
        "randomize_questions": False,
        "randomize_options": False,
    }

    def _surveys(self):
        rows, tr = [], []
        for r in self.q("""
                select id, status, assessment_type, display_option, is_timed, is_evaluable,
                       evaluation_type, use_score, use_classifications, use_recommendations,
                       use_actions, allow_end_based_on_answer_repeat, answers_count_to_end,
                       end_based_on_answer_repeat_in_row,
                       allow_update_answer_options_scores_based_on_classification,
                       allow_update_answer_options_text_based_on_classification,
                       create_option_for_each_classification, created_at, updated_at,
                       deleted_at, category_id, sponsor_id,
                       title, description, short_description, language
                from assessments_assessment"""):
            (lid, status, atype, disp, is_timed, is_eval, etype, use_score, use_cls,
             use_rec, use_act, allow_end, cnt_end, end_row, upd_score, upd_text,
             opt_each, created, updated, deleted, cat, sponsor,
             title, desc, short, lang) = r
            tid = self.m("survey", lid)
            rows.append((lid, (
                tid, status, map_survey_type(atype), map_display_option(disp), is_timed,
                True,  # is_for_child -- ruled true for every migrated row
                is_eval, etype, use_score, use_cls, use_rec, use_act, allow_end,
                cnt_end, end_row, upd_score, upd_text, opt_each, created, updated,
                deleted, self.cat_map.get(cat), map_sponsor(sponsor))))
            tr.append((tid, lang or DEFAULT_LANGUAGE, title, desc, short))

        ins, upd = self._split("survey", rows)
        self._write("surveys_survey", self.SURVEY_COLS, ins, upd,
                    insert_only=dict(self.SURVEY_INSERT_ONLY,
                                     organization_id=self.org_id))
        self._translations("surveys_surveytranslation", "survey_id",
                           ["title", "description", "short_description"], tr)

    # -- sections / questions ------------------------------------------------

    SECTION_COLS = ["id", "survey_id", "title", "description", "order", "is_hidden",
                    "submit_action", "created_at", "updated_at", "deleted_at"]

    def _sections(self):
        self.section_lang = {}
        survey_lang = dict(self.q("select id, coalesce(language, %s) "
                                  "from assessments_assessment", (DEFAULT_LANGUAGE,)))
        rows, tr = [], []
        for (lid, aid, title, desc, order, hidden, action,
             created, updated, deleted) in self.q(
                "select id, assessment_id, title, description, \"order\", is_hidden, "
                "submit_action, created_at, updated_at, deleted_at from assessments_section"):
            tid = self.m("section", lid)
            lang = survey_lang.get(aid, DEFAULT_LANGUAGE)
            self.section_lang[lid] = lang
            rows.append((lid, (tid, self.m("survey", aid), title, desc, order, hidden,
                               map_submit_action(action), created, updated, deleted)))
            tr.append((tid, lang, title, desc))
        ins, upd = self._split("section", rows)
        self._write("surveys_section", self.SECTION_COLS, ins, upd)
        self._translations("surveys_sectiontranslation", "section_id",
                           ["title", "description"], tr)

    QUESTION_COLS = ["id", "survey_id", "section_id", "title", "description",
                     "answer_time", "order", "is_required", "type",
                     "created_at", "updated_at", "deleted_at"]

    def _questions(self):
        rows, tr = [], []
        for (lid, aid, sid, title, desc, atime, order, req, qtype,
             created, updated, deleted) in self.q(
                "select id, assessment_id, section_id, title, description, answer_time, "
                "\"order\", is_required, type, created_at, updated_at, deleted_at "
                "from assessments_question"):
            tid = self.m("question", lid)
            rows.append((lid, (tid, self.m("survey", aid), self.m("section", sid),
                               title, desc, atime, order, req, qtype,
                               created, updated, deleted)))
            tr.append((tid, self.section_lang.get(sid, DEFAULT_LANGUAGE), title, desc))
        ins, upd = self._split("question", rows)
        self._write("surveys_question", self.QUESTION_COLS, ins, upd)
        self._translations("surveys_questiontranslation", "question_id",
                           ["title", "description"], tr)

    # -- answer schemas ------------------------------------------------------

    SCHEMA_COLS = ["id", "survey_id", "section_id", "question_id",
                   "type", "with_file", "is_mcq", "is_grid"]

    def _schemas(self):
        rows = []
        for lid, aid, sid, qid, stype, wfile, mcq, grid in self.q(
                "select id, assessment_id, section_id, question_id, type, with_file, "
                "is_mcq, is_grid from assessments_answerschema"):
            rows.append((lid, (self.m("schema", lid), self.m("survey", aid),
                               self.m("section", sid), self.m("question", qid),
                               stype, wfile, mcq, grid)))
        ins, upd = self._split("schema", rows)
        self._write("surveys_answerschema", self.SCHEMA_COLS, ins, upd)

    OPTION_COLS = ["id", "survey_id", "section_id", "question_id", "schema_id",
                   "classification_id", "text", "score", "order",
                   "is_row", "is_column", "ending_option"]

    def _options(self):
        """`order` is nullable in legacy and NOT NULL here, so a null falls back
        to the row's position within its schema rather than to a constant --
        a constant would collapse the ordering of every option in that schema."""
        rows, tr = [], []
        for (lid, aid, sid, qid, schema, cls, text, score, order,
             is_row, is_col, ending, fallback) in self.q("""
                select id, assessment_id, section_id, question_id, schema_id,
                       classification_id, text, score, "order", is_row, is_column,
                       ending_option,
                       row_number() over (partition by schema_id order by "order" nulls last, id)
                from assessments_answerschemaoption"""):
            tid = self.m("option", lid)
            rows.append((lid, (tid, self.m("survey", aid), self.m("section", sid),
                               self.m("question", qid), self.m("schema", schema),
                               self.m("classification", cls) if cls else None,
                               text, score,
                               order if order is not None else fallback,
                               is_row, is_col, ending)))
            tr.append((tid, self.section_lang.get(sid, DEFAULT_LANGUAGE), text))
        ins, upd = self._split("option", rows)
        self._write("surveys_answerschemaoption", self.OPTION_COLS, ins, upd)
        self._translations("surveys_answerschemaoptiontranslation", "option_id",
                           ["text"], tr)

    # -- classifications / actions / recommendations -------------------------

    def _classifications(self):
        rows, tr = [], []
        survey_lang = dict(self.q("select id, coalesce(language, %s) "
                                  "from assessments_assessment", (DEFAULT_LANGUAGE,)))
        for lid, aid, name, score, created, updated, deleted in self.q(
                "select id, assessment_id, name, score, created_at, updated_at, deleted_at "
                "from assessments_classification"):
            tid = self.m("classification", lid)
            rows.append((lid, (tid, self.m("survey", aid), score,
                               created, updated, deleted)))
            tr.append((tid, survey_lang.get(aid, DEFAULT_LANGUAGE), name))
        ins, upd = self._split("classification", rows)
        self._write("classifications_classification",
                    ["id", "survey_id", "score", "created_at", "updated_at", "deleted_at"],
                    ins, upd)
        self._translations("classifications_classificationtranslation",
                           "classification_id", ["name"], tr)

    def _actions(self):
        rows, tr = [], []
        survey_lang = dict(self.q("select id, coalesce(language, %s) "
                                  "from assessments_assessment", (DEFAULT_LANGUAGE,)))
        for lid, aid, title, desc, upper, lower in self.q(
                "select id, assessment_id, title, description, upper_limit, lower_limit "
                "from assessments_action"):
            tid = self.m("action", lid)
            rows.append((lid, (tid, self.m("survey", aid), upper, lower)))
            tr.append((tid, survey_lang.get(aid, DEFAULT_LANGUAGE), title, desc))
        ins, upd = self._split("action", rows)
        self._write("recommendations_action",
                    ["id", "survey_id", "upper_limit", "lower_limit"], ins, upd)
        self._translations("recommendations_actiontranslation", "action_id",
                           ["title", "description"], tr)

    def _recommendations(self):
        rows, tr = [], []
        survey_lang = dict(self.q("select id, coalesce(language, %s) "
                                  "from assessments_assessment", (DEFAULT_LANGUAGE,)))
        for lid, aid, oid, desc, created, updated, deleted in self.q(
                "select id, assessment_id, option_id, description, created_at, updated_at, "
                "deleted_at from assessments_recommendation"):
            tid = self.m("recommendation", lid)
            rows.append((lid, (tid, self.m("survey", aid), self.m("option", oid),
                               created, updated, deleted)))
            tr.append((tid, survey_lang.get(aid, DEFAULT_LANGUAGE), desc))
        ins, upd = self._split("recommendation", rows)
        self._write("recommendations_recommendation",
                    ["id", "survey_id", "option_id", "created_at", "updated_at", "deleted_at"],
                    ins, upd)
        self._translations("recommendations_recommendationtranslation",
                           "recommendation_id", ["description"], tr)

    # -- collections ---------------------------------------------------------

    COLLECTION_COLS = ["id", "status", "type", "category_id", "sponsor",
                       "created_at", "updated_at", "deleted_at"]

    def _collections(self):
        rows, tr_by_collection = [], defaultdict(list)
        for (lid, status, ctype, cat, sponsor, title, desc, short, slug, lang,
             created, updated, deleted) in self.q("""
                select id, status, type, category_id, sponsor_id, title, description,
                       short_description, slug, language, created_at, updated_at, deleted_at
                from blogs_blog"""):
            tid = self.m("collection", lid)
            rows.append((lid, (tid, map_collection_status(status), ctype,
                               self.cat_map.get(cat),
                               map_sponsor(sponsor), created, updated, deleted)))
            langs = set(title or {}) | set(desc or {}) | set(short or {})
            for l in (langs or {lang or DEFAULT_LANGUAGE}):
                tr_by_collection[tid].append(
                    (l, (title or {}).get(l), (desc or {}).get(l),
                     (short or {}).get(l), slug))
        ins, upd = self._split("collection", rows)
        self._write("survey_collections_surveycollection", self.COLLECTION_COLS, ins, upd,
                    insert_only={"organization_id": self.org_id})

        # This translation table has no (collection, language) unique constraint
        # and a serial pk, so it cannot be upserted -- replace what we own.
        #
        # `seo` is read back and re-supplied rather than dropped: it is not part
        # of the migration, but delete-then-insert would otherwise reset it to
        # NULL on every collection this load touches.
        owned = list(tr_by_collection)
        if owned:
            keep_seo = dict(self.t(
                "select collection_id || '|' || language, seo "
                "from survey_collections_surveycollectiontranslation "
                "where collection_id = any(%s)", (owned,)))
            self.cur.execute(
                "delete from survey_collections_surveycollectiontranslation "
                "where collection_id = any(%s)", (owned,))
            # Explicit ids, not the serial default: a nextval is consumed even
            # when the insert is later rolled back, so a dry run that let the
            # default fire moved this sequence by +78 every time it ran.
            nxt = self._allocator("survey_collections_surveycollectiontranslation")
            payload = [(nxt(), cid, l, t, d, s, slug, keep_seo.get(f"{cid}|{l}"))
                       for cid, items in tr_by_collection.items()
                       for (l, t, d, s, slug) in items]
            self.cur.executemany(
                "insert into survey_collections_surveycollectiontranslation "
                '(id, collection_id, language, title, description, short_description, '
                "slug, seo) values (%s, %s, %s, %s, %s, %s, %s, %s)", payload)
            for row in payload:
                self.expected["survey_collections_surveycollectiontranslation"][row[0]] = {
                    "collection_id": row[1], "language": row[2], "title": row[3],
                    "description": row[4], "short_description": row[5], "slug": row[6]}
            self.say(f"  {'survey_collections_surveycollectiontranslation':<44}"
                     f"{len(payload):>7} translations")

        self._collection_membership()

    def _collection_membership(self):
        """The legacy generic FK (content_type_id, object_id) on a survey is the
        target's explicit M2M. The old importer loaded one of these links; the
        legacy database has 120."""
        ct = self.q("select id from django_content_type "
                    "where app_label='blogs' and model='blog'")
        if not ct:
            self.say("  no blogs.blog content type -- no collection membership to load")
            return
        blog_ct = ct[0][0]
        pairs = []
        for aid, oid in self.q(
                "select id, object_id from assessments_assessment "
                "where content_type_id = %s and object_id is not null", (blog_ct,)):
            if oid not in self.maps["collection"]:
                raise SystemExit(f"survey {aid} points at blog {oid}, which does not exist")
            pairs.append((self.m("collection", oid), self.m("survey", aid)))

        # Filtered here rather than with ON CONFLICT DO NOTHING: the conflict is
        # only detected after the serial default has already fired, so every dry
        # run burned 120 values off this sequence and never gave them back.
        have = {tuple(r) for r in self.t(
            "select surveycollection_id, survey_id "
            "from survey_collections_surveycollection_assessments")}
        new = [p for p in pairs if p not in have]
        if new:
            nxt = self._allocator("survey_collections_surveycollection_assessments")
            self.cur.executemany(
                "insert into survey_collections_surveycollection_assessments "
                "(id, surveycollection_id, survey_id) values (%s, %s, %s)",
                [(nxt(), c, s) for c, s in new])
        self.m2m_pairs = pairs
        self.say(f"  {'survey_collections_surveycollection_assessments':<44}"
                 f"{len(new):>7} links added ({len(pairs) - len(new)} already present)")

    # -- stale rows ----------------------------------------------------------

    def _prune_stale(self):
        """Remove rows the previous importer left behind that legacy has dropped.

        The load only ever inserts or updates, so a row the old importer created
        and legacy has since deleted simply stays. Question 356 is the live case:
        legacy holds options 12804-12806, the old importer had already written
        the same three as 1363-1365, the witness does not match them, and the
        question ends up rendering six options with orders 1,2,3,1,2,3 -- one
        pair disagreeing on text, and the stale trio carrying no translations.

        The tempting rule -- delete anything under a migrated survey that legacy
        does not claim -- is wrong and would destroy real data: section 235,
        questions 3080-3082 and options 12786-12788 are genuine rows created in
        the new system during 2026, inside surveys the old importer had made.
        Nothing distinguishes them from stale rows by parentage alone.

        So the rule is narrow enough to be provable: an unclaimed option is
        pruned only when it duplicates the (schema, order) of an option this
        load claims -- which is exactly the user-visible defect and nothing
        else. Everything else unclaimed is reported and left alone.
        """
        self.say("")
        self.say("stale rows (present in the target, no longer in legacy):")

        claimed_opts = set(self.maps["option"].values())
        claimed_schemas = {r["schema_id"] for r in
                           self.expected["surveys_answerschemaoption"].values()}
        rows = self.t(
            'select id, schema_id, "order" from surveys_answerschemaoption '
            "where schema_id = any(%s)", (list(claimed_schemas),))
        claimed_slots = {(s, o) for i, s, o in rows if i in claimed_opts}
        prune_opts = sorted(i for i, s, o in rows
                            if i not in claimed_opts and (s, o) in claimed_slots)

        claimed_recs = set(self.maps["recommendation"].values())
        prune_recs = sorted(r[0] for r in self.t(
            "select id from recommendations_recommendation where option_id = any(%s)",
            (prune_opts,))) if prune_opts else []
        prune_recs = [r for r in prune_recs if r not in claimed_recs]

        self._refuse_if_referenced("surveys_answerschemaoption", prune_opts,
                                   ignore={"surveys_answerschemaoptiontranslation",
                                           "recommendations_recommendation"})
        self._refuse_if_referenced("recommendations_recommendation", prune_recs,
                                   ignore={"recommendations_recommendationtranslation"})

        if prune_recs:
            self.cur.execute("delete from recommendations_recommendationtranslation "
                             "where recommendation_id = any(%s)", (prune_recs,))
            self.cur.execute("delete from recommendations_recommendation where id = any(%s)",
                             (prune_recs,))
        if prune_opts:
            self.cur.execute("delete from surveys_answerschemaoptiontranslation "
                             "where option_id = any(%s)", (prune_opts,))
            self.cur.execute("delete from surveys_answerschemaoption where id = any(%s)",
                             (prune_opts,))
        self.pruned = {"surveys_answerschemaoption": prune_opts,
                       "recommendations_recommendation": prune_recs}
        self.say(f"  {'surveys_answerschemaoption':<44}{len(prune_opts):>7} pruned "
                 f"{prune_opts if prune_opts else ''}")
        self.say(f"  {'recommendations_recommendation':<44}{len(prune_recs):>7} pruned "
                 f"{prune_recs if prune_recs else ''}")

        self._prune_default_translations()

    # Translation tables where the previous importer wrote rows tagged
    # language='default'. Django's language codes are 'ar' and 'en'; 'default'
    # is not one, so nothing can ever request these rows -- but they sit
    # alongside the DEFAULT_LANGUAGE row this load writes for the same parent.
    #   table, parent fk column, id map name, text columns
    DEFAULT_LANG_TABLES = [
        ("recommendations_recommendationtranslation", "recommendation_id",
         "recommendation", ("description",)),
        ("classifications_classificationtranslation", "classification_id",
         "classification", ("name",)),
        ("recommendations_actiontranslation", "action_id",
         "action", ("title", "description")),
    ]

    def _prune_default_translations(self):
        """Drop the importer's language='default' rows this load has superseded.

        The old importer tagged every translation it wrote 'default'. That is
        not a language code the app can ask for, so those rows were already
        unreachable; what makes them worth removing is that this load now writes
        a real DEFAULT_LANGUAGE row against the same parent, leaving two
        translations per parent where the schema means there to be one.

        Same discipline as the option rule above: a 'default' row is deleted
        only when this load wrote a DEFAULT_LANGUAGE row for the same parent AND
        every text column is identical. Anything that disagrees is text the
        importer holds and legacy does not -- that is a finding, not a duplicate,
        so it is reported and left in place for a person to look at.
        """
        for table, fk, map_name, cols in self.DEFAULT_LANG_TABLES:
            claimed = set(self.maps[map_name].values())
            if not claimed:
                continue
            same = " and ".join(
                f"d.{c} is not distinct from k.{c}" for c in cols)
            ids = [r[0] for r in self.t(
                f"select d.id from {table} d join {table} k "
                f"  on k.{fk} = d.{fk} and k.language = %s "
                f"where d.language = 'default' and d.{fk} = any(%s) and {same}",
                (DEFAULT_LANGUAGE, list(claimed)))]
            differs = [r[0] for r in self.t(
                f"select d.id from {table} d join {table} k "
                f"  on k.{fk} = d.{fk} and k.language = %s "
                f"where d.language = 'default' and d.{fk} = any(%s) and not ({same})",
                (DEFAULT_LANGUAGE, list(claimed)))]
            if ids:
                self.cur.execute(f"delete from {table} where id = any(%s)", (ids,))
            self.pruned[table] = ids
            note = ""
            if differs:
                note = self.style.WARNING(
                    f"  <- {len(differs)} left in place: their text disagrees with legacy")
            self.say(f"  {table:<44}{len(ids):>7} pruned (language='default'){note}")

    def _refuse_if_referenced(self, table, ids, ignore=()):
        """Never delete a row something else points at.

        The foreign keys are discovered from the catalog rather than listed, so
        a table added later is covered without anyone remembering to come back.
        """
        if not ids:
            return
        fks = self.t(
            "select c.conrelid::regclass::text, a.attname from pg_constraint c "
            "join unnest(c.conkey) k on true "
            "join pg_attribute a on a.attrelid = c.conrelid and a.attnum = k "
            "where c.contype = 'f' and c.confrelid::regclass::text = %s", (table,))
        for child, col in fks:
            if child in ignore:
                continue
            n = self.t(f'select count(*) from {child} where "{col}" = any(%s)', (ids,))[0][0]
            if n:
                raise SystemExit(
                    f"refusing to prune {n} row(s) of {table}: {child}.{col} still "
                    f"references them. Something in the new system is using data the "
                    f"migration was about to delete -- resolve that by hand first.")

    def _section_targets(self):
        """Second pass: the self-FK could not be set before every section existed.
        Null on all 213 legacy rows today; implemented so it stays correct."""
        rows = [(self.m("section", tgt), self.m("section", lid))
                for lid, tgt in self.q(
                    "select id, submit_action_target_id from assessments_section "
                    "where submit_action_target_id is not null")]
        if rows:
            self.cur.executemany(
                "update surveys_section set submit_action_target_id = %s where id = %s", rows)
        self.say(f"  {'surveys_section.submit_action_target':<44}{len(rows):>7} set")

    # -- sequences -----------------------------------------------------------

    SEQUENCED = [
        "surveys_survey", "surveys_section", "surveys_question",
        "surveys_answerschema", "surveys_answerschemaoption",
        "classifications_classification", "recommendations_action",
        "recommendations_recommendation", "survey_collections_surveycollection",
        "survey_collections_surveycollectiontranslation",
        "survey_collections_surveycollection_assessments",
    ]

    def _plan_sequences(self):
        """Report what the sequences will need, without touching them.

        setval() is NOT rolled back. Calling it inside this transaction meant a
        dry run permanently moved production sequences -- and to a value derived
        from rows that were about to be discarded, so recommendations went from
        4 to 12,919 on a database whose rows never changed. The repair therefore
        waits until after COMMIT; see _apply_sequences.
        """
        self.say("")
        self.say("sequences (reported here, set after commit):")
        self.seq_plan = []
        for table in self.SEQUENCED:
            seq = self.t("select pg_get_serial_sequence(%s, 'id')", (table,))[0][0]
            if not seq:
                self.say(f"  {table:<48} no sequence")
                continue
            current = self.t(f"select last_value from {seq}")[0][0]
            want = self.t(f"select coalesce(max(id), 1) from {table}")[0][0]
            self.seq_plan.append(table)
            flag = "  <- behind max(id)" if current < want else ""
            self.say(f"  {table:<48}{current:>8} -> {want:<8}{flag}")

    def _apply_sequences(self):
        """Runs after COMMIT, in its own transaction, reading committed state."""
        self.say("")
        self.say("setting sequences:")
        with connection.cursor() as cur:
            for table in self.seq_plan:
                cur.execute("select pg_get_serial_sequence(%s, 'id')", (table,))
                seq = cur.fetchone()[0]
                cur.execute(f"select last_value from {seq}")
                before = cur.fetchone()[0]
                cur.execute(
                    f"select setval(%s, coalesce((select max(id) from {table}), 1), true)",
                    (seq,))
                cur.execute(f"select last_value from {seq}")
                after = cur.fetchone()[0]
                flag = "  <- was behind max(id)" if before < after else ""
                self.say(f"  {table:<48}{before:>8} -> {after:<8}{flag}")

    # -- verification --------------------------------------------------------

    # Entities whose text lives in a translation table. Every one of these was
    # previously unverified: the only line in _verify that mentioned a
    # translation computed a count, printed it, and never raised on it. A run
    # sabotaged to drop all 159 survey translations -- and delete the ones
    # already there -- still printed "verification passed".
    TRANSLATED = [
        ("surveys_survey", "surveys_surveytranslation", "survey_id"),
        ("surveys_section", "surveys_sectiontranslation", "section_id"),
        ("surveys_question", "surveys_questiontranslation", "question_id"),
        ("surveys_answerschemaoption", "surveys_answerschemaoptiontranslation", "option_id"),
        ("classifications_classification",
         "classifications_classificationtranslation", "classification_id"),
        ("recommendations_action", "recommendations_actiontranslation", "action_id"),
        ("recommendations_recommendation",
         "recommendations_recommendationtranslation", "recommendation_id"),
        ("survey_collections_surveycollection",
         "survey_collections_surveycollectiontranslation", "collection_id"),
    ]

    @staticmethod
    def _same(a, b):
        from decimal import Decimal
        if a is None or b is None:
            return a is None and b is None
        if isinstance(a, Decimal) or isinstance(b, Decimal):
            return Decimal(str(a)) == Decimal(str(b))
        if hasattr(a, "tzinfo") and hasattr(b, "tzinfo"):
            return _ms(a) == _ms(b)
        if isinstance(a, str) or isinstance(b, str):
            return str(a) == str(b)
        return a == b

    def _verify_contents(self, problems):
        """Read every written row back and compare it column by column.

        Counting rows cannot fail: the ids counted are the ids just written, so
        they are present by construction. This reads the values instead.
        """
        for table, expected in sorted(self.expected.items()):
            if not expected:
                continue
            sample = next(iter(expected.values()))
            cols = list(sample)
            keyed_by_pk = not isinstance(next(iter(expected)), tuple)
            names = ", ".join(f'"{c}"' for c in cols)
            if keyed_by_pk:
                pk = "category_id" if table == "taxonomy_category" else "id"
                if pk not in cols:
                    continue
                # ::text on both sides: these keys are integers on most tables
                # and UUIDs on the taxonomy ones, and a uuid column compared
                # against a text array matches nothing rather than erroring.
                rows = self.t(f'select {names} from {table} where "{pk}"::text = any(%s)',
                              ([str(k) for k in expected],))
                actual = {str(dict(zip(cols, r))[pk]): dict(zip(cols, r)) for r in rows}
                expected = {str(k): v for k, v in expected.items()}
            else:
                fk, lang = cols[0], cols[1]
                rows = self.t(f'select {names} from {table} where "{fk}"::text = any(%s)',
                              ([str(k[0]) for k in expected],))
                actual = {(str(d[fk]), d[lang]): d
                          for d in (dict(zip(cols, r)) for r in rows)}
                expected = {(str(k[0]), k[1]): v for k, v in expected.items()}

            missing = [k for k in expected if k not in actual]
            wrong = []
            for key, want in expected.items():
                got = actual.get(key)
                if got is None:
                    continue
                for c in cols:
                    if not self._same(want[c], got[c]):
                        wrong.append((key, c, want[c], got[c]))
                        break
            if missing or wrong:
                problems.append(
                    f"{table}: {len(missing)} row(s) written but not readable back, "
                    f"{len(wrong)} row(s) hold a value this load did not write "
                    f"(e.g. {wrong[0] if wrong else missing[0]})")
            self.say(f"  {'matches' if not (missing or wrong) else 'MISMATCH':<9}"
                     f"{table:<48}{len(expected):>7} rows")

    def _verify_translations(self, problems):
        """Every row this load wrote must carry the text that goes with it."""
        for base, tt, fk in self.TRANSLATED:
            ids = sorted(self.expected.get(base, {}))
            if not ids or isinstance(ids[0], tuple):
                continue
            n = self.t(
                f"select count(*) from unnest(%s::bigint[]) x(id) "
                f"where not exists (select 1 from {tt} t where t.{fk} = x.id)",
                (ids,))[0][0]
            if n:
                problems.append(f"{tt}: {n} of {len(ids)} {base} row(s) have no translation")
            self.say(f"  {'translated' if not n else 'UNTRANSLATED':<12}"
                     f"{tt:<45}{len(ids) - n:>7}/{len(ids)}")

    # legacy table, legacy column, id-map key, target translation table, fk,
    # target column. The text payload of the migration, checked against the
    # source rather than against what the loader believed it was writing.
    SOURCE_TEXT = [
        ("assessments_assessment", "title", "survey",
         "surveys_surveytranslation", "survey_id", "title"),
        ("assessments_assessment", "description", "survey",
         "surveys_surveytranslation", "survey_id", "description"),
        ("assessments_assessment", "short_description", "survey",
         "surveys_surveytranslation", "survey_id", "short_description"),
        ("assessments_section", "title", "section",
         "surveys_sectiontranslation", "section_id", "title"),
        ("assessments_section", "description", "section",
         "surveys_sectiontranslation", "section_id", "description"),
        ("assessments_question", "title", "question",
         "surveys_questiontranslation", "question_id", "title"),
        ("assessments_question", "description", "question",
         "surveys_questiontranslation", "question_id", "description"),
        ("assessments_answerschemaoption", "text", "option",
         "surveys_answerschemaoptiontranslation", "option_id", "text"),
        ("assessments_classification", "name", "classification",
         "classifications_classificationtranslation", "classification_id", "name"),
        ("assessments_action", "title", "action",
         "recommendations_actiontranslation", "action_id", "title"),
        ("assessments_action", "description", "action",
         "recommendations_actiontranslation", "action_id", "description"),
        ("assessments_recommendation", "description", "recommendation",
         "recommendations_recommendationtranslation", "recommendation_id", "description"),
    ]

    def _verify_against_source(self, problems):
        """Compare the target's text with the legacy database, not with the loader.

        _verify_contents compares what is in the target against what this run
        intended to write, so it catches a write that failed but agrees with the
        loader about a value the loader got wrong. Proven: sabotaging _surveys to
        write 'CORRUPTED' as one title passed every other check, because the
        expectation was corrupted in exactly the same way.

        This reads the legacy value instead, follows the id map, and compares.
        A transform bug, a column swap, or a row written under the wrong id all
        surface here and nowhere else.

        What it deliberately cannot check: a column carried under a *ruling*.
        Inverting SPONSOR_MAP passes every check here, and must -- the swap is
        the agreed answer, so nothing in the data distinguishes the ruling from
        a mistake in it. Those columns are verified by the ruling being right,
        which is a conversation, not an assertion. Hence text only: text is the
        one payload where legacy and target are supposed to agree verbatim.
        """
        for lt, lc, key, tt, fk, tc in self.SOURCE_TEXT:
            legacy = {self.maps[key][i]: v
                      for i, v in self.q(f'select id, "{lc}" from {lt}')
                      if i in self.maps[key]}
            target = dict(self.t(
                f'select "{fk}", "{tc}" from {tt} where "{fk}" = any(%s)',
                (list(legacy),)))
            bad = [(tid, legacy[tid], target.get(tid))
                   for tid in legacy if not self._same(legacy[tid], target.get(tid))]
            if bad:
                problems.append(
                    f"{tt}.{tc}: {len(bad)} row(s) do not match {lt}.{lc} in the source "
                    f"(e.g. {tt} {bad[0][0]}: source {bad[0][1]!r}, target {bad[0][2]!r})")
            self.say(f"  {'source-ok' if not bad else 'CORRUPTED':<11}"
                     f"{tt + '.' + tc:<46}{len(legacy) - len(bad):>7}/{len(legacy)}")

    def _verify(self):
        """Runs inside the transaction, so a dry run checks the would-be state."""
        self.say("")
        self.say("verification:")
        problems = []

        pairs = [
            ("assessments_assessment", "surveys_survey", "survey"),
            ("assessments_section", "surveys_section", "section"),
            ("assessments_question", "surveys_question", "question"),
            ("assessments_answerschema", "surveys_answerschema", "schema"),
            ("assessments_answerschemaoption", "surveys_answerschemaoption", "option"),
            ("assessments_classification", "classifications_classification", "classification"),
            ("assessments_action", "recommendations_action", "action"),
            ("assessments_recommendation", "recommendations_recommendation", "recommendation"),
        ]
        for lt, tt, key in pairs:
            want = self.q(f"select count(*) from {lt}")[0][0]
            have = self.t(f"select count(*) from {tt} where id = any(%s)",
                          (list(self.maps[key].values()),))[0][0]
            ok = want == have
            if not ok:
                problems.append(f"{tt}: {want} legacy rows resolved to {have} present rows")
            self.say(f"  {'present' if ok else 'MISSING':<9}{tt:<40}{have:>7}/{want}")

        # no imported row may have landed on a row we did not resolve
        orphan = self.t(
            "select count(*) from surveys_section s "
            "left join surveys_survey v on v.id = s.survey_id where v.id is null")[0][0]
        if orphan:
            problems.append(f"{orphan} sections point at a survey that does not exist")

        dangling = self.t(
            "select count(*) from surveys_answerschemaoption o "
            "left join surveys_answerschema s on s.id = o.schema_id where s.id is null")[0][0]
        if dangling:
            problems.append(f"{dangling} options point at a schema that does not exist")

        self._verify_contents(problems)
        self._verify_translations(problems)
        self._verify_against_source(problems)

        # organization_id gates every domain event. A null one is not a database
        # error and not a visible one either -- messaging.py logs a skip and the
        # row silently never reaches any consumer.
        if self.org_id:
            unpublishable = self.t(
                "select count(*) from surveys_survey where id = any(%s) "
                "and organization_id is null", (list(self.maps["survey"].values()),))[0][0]
            unpublishable += self.t(
                "select count(*) from survey_collections_surveycollection where id = any(%s) "
                "and organization_id is null",
                (list(self.maps["collection"].values()),))[0][0]
            if unpublishable:
                problems.append(f"{unpublishable} migrated row(s) have no organization_id "
                                f"and could never be published")
            self.say(f"  {'publishable' if not unpublishable else 'UNPUBLISHABLE':<12}"
                     f"{'organization_id present on migrated rows':<45}")

        # The defect _prune_stale exists to fix, checked rather than assumed.
        dupe_order = self.t(
            'select count(*) from (select schema_id, "order" from surveys_answerschemaoption '
            "where schema_id = any(%s) group by 1, 2 having count(*) > 1) d",
            (sorted({r["schema_id"] for r in
                     self.expected["surveys_answerschemaoption"].values()}),))[0][0]
        if dupe_order:
            problems.append(f"{dupe_order} schema(s) still have two options sharing an "
                            f"\"order\" -- their display order is a coin toss")

        missing_links = self.t(
            "select count(*) from unnest(%s::bigint[], %s::bigint[]) x(c, s) "
            "where not exists (select 1 from "
            "survey_collections_surveycollection_assessments m "
            "where m.surveycollection_id = x.c and m.survey_id = x.s)",
            ([p[0] for p in self.m2m_pairs], [p[1] for p in self.m2m_pairs]))[0][0]
        if missing_links:
            problems.append(f"{missing_links} collection membership link(s) are absent")
        self.say(f"  {'linked' if not missing_links else 'MISSING':<12}"
                 f"{'collection membership':<45}"
                 f"{len(self.m2m_pairs) - missing_links:>7}/{len(self.m2m_pairs)}")

        bad_choice = self.t(
            "select survey_type, count(*) from surveys_survey "
            "where survey_type not in "
            "('survey','assessment','curriculum','exam','form') group by 1")
        # Reported, not fatal: these are genuine rows this load never touches.
        # `choices` is not a database constraint, so the new system wrote a value
        # its own model forbids. Worth fixing, but not by this command.
        for value, n in bad_choice:
            self.say(self.style.WARNING(
                f"  pre-existing  survey_type {value!r} on {n} genuine row(s) is not a "
                f"model choice -- not written by this load"))

        self.say("")
        if problems:
            self.say(self.style.ERROR("verification failed:"))
            for p in problems:
                self.say(f"  - {p}")
            raise SystemExit(1)
        self.say(self.style.SUCCESS("verification passed"))

    # -- id map --------------------------------------------------------------

    def _write_id_map(self, path):
        payload = {
            table: {str(lid): {"target_id": str(tid),
                               "mode": self.modes[table][lid].value}
                    for lid, tid in mapping.items()}
            for table, mapping in self.maps.items()
        }
        # "match-or-mint" told the reader nothing: a matched UUID belongs to a
        # category that already existed, a minted one was created by this run.
        payload["category"] = {
            str(k): {"target_id": str(v),
                     "mode": "mint" if v in getattr(self, "minted_categories", set())
                             else "match"}
            for k, v in getattr(self, "cat_map", {}).items()}
        payload["pruned"] = {t: ids for t, ids in getattr(self, "pruned", {}).items()}
        with open(path, "w") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        self.say(f"id map written to {path}")

"""Check the legacy database against the agreed mapping. Writes nothing.

Every assertion here corresponds to something the previous importer assumed
without checking. Run this before `legacy_load` and read the collision report:
ids that a genuine row already owns cannot be preserved.
"""

from django.core.management.base import BaseCommand
from django.db import connection

from surveys.management.commands.legacy_load import RUN_MARKER
from surveys.migration_spec.resolve import Mode, _ms, resolve, resolve_by_witness
from surveys.migration_spec.spec import (
    DISPLAY_OPTION_MAP,
    SPONSOR_MAP,
    SUBMIT_ACTION_MAP,
    SURVEY_TYPE_MAP,
    TABLES,
    assert_total,
)

# name, legacy table, target table, legacy witness, target witness, timestamped,
# resolver -- exactly the witnesses and resolvers legacy_load._resolve_all uses.
# Timestamped rows are witnessed by created_at (truncated to milliseconds, which
# is all the target column kept); the other three carry no timestamp and are
# witnessed by their parent chain. Collections take resolve_by_witness rather
# than resolve, because the old importer renumbered them: a collection's id
# witnesses nothing, so only created_at can say which target row is which.
RESOLVED = [
    ("survey", "assessments_assessment", "surveys_survey",
     "created_at", "created_at", True, resolve),
    ("section", "assessments_section", "surveys_section",
     "created_at", "created_at", True, resolve),
    ("question", "assessments_question", "surveys_question",
     "created_at", "created_at", True, resolve),
    ("classification", "assessments_classification", "classifications_classification",
     "created_at", "created_at", True, resolve),
    ("recommendation", "assessments_recommendation", "recommendations_recommendation",
     "created_at", "created_at", True, resolve),
    ("schema", "assessments_answerschema", "surveys_answerschema",
     "assessment_id, section_id, question_id", "survey_id, section_id, question_id", False, resolve),
    ("option", "assessments_answerschemaoption", "surveys_answerschemaoption",
     "assessment_id, section_id, question_id, schema_id",
     "survey_id, section_id, question_id, schema_id", False, resolve),
    ("action", "assessments_action", "recommendations_action",
     "assessment_id", "survey_id", False, resolve),
    ("collection", "blogs_blog", "survey_collections_surveycollection",
     "created_at", "created_at", True, resolve_by_witness),
]


class Command(BaseCommand):
    help = "Validate the legacy database against the agreed column mapping. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--legacy-dsn", required=True,
                            help="libpq connection string for the legacy database")

    def handle(self, *args, **opts):
        import psycopg

        self.failures = []
        with psycopg.connect(opts["legacy_dsn"]) as src:
            self._coverage(src)
            self._values(src)
            self._shape(src)
            self._collisions(src)

        self.stdout.write("")
        if self.failures:
            self.stdout.write(self.style.ERROR(f"{len(self.failures)} blocking problem(s):"))
            for f in self.failures:
                self.stdout.write(f"  - {f}")
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("preflight clean -- the mapping holds against this data"))

    # -- checks --------------------------------------------------------------

    def _coverage(self, src):
        rows = src.execute(
            "select table_name, column_name from information_schema.columns "
            "where table_schema='public'"
        ).fetchall()
        cols = {}
        for t, c in rows:
            cols.setdefault(t, set()).add(c)
        assert_total(cols)
        mapped = sum(len(t.columns) for t in TABLES)
        self.stdout.write(self.style.SUCCESS(
            f"coverage      OK  {len(TABLES)} tables, {mapped} columns, none unaccounted for"))

    def _values(self, src):
        checks = [
            ("assessment_type", "assessments_assessment", "assessment_type", set(SURVEY_TYPE_MAP)),
            ("display_option", "assessments_assessment", "display_option", set(DISPLAY_OPTION_MAP)),
            ("submit_action", "assessments_section", "submit_action", set(SUBMIT_ACTION_MAP)),
        ]
        for label, table, col, allowed in checks:
            bad = src.execute(
                f"select {col}, count(*) from {table} "
                f"where {col} is not null and {col} <> '' and {col} <> ALL(%s) group by 1",
                (list(allowed),),
            ).fetchall()
            if bad:
                detail = ", ".join(f"{v!r} x{n}" for v, n in bad)
                self.failures.append(f"{table}.{col}: unmappable values -- {detail}")
            else:
                self.stdout.write(self.style.SUCCESS(f"{label:<14}OK  all values map"))

        bad = src.execute(
            "select sponsor_id, count(*) from assessments_assessment "
            "where sponsor_id is not null and sponsor_id <> ALL(%s) group by 1",
            (list(SPONSOR_MAP),),
        ).fetchall()
        if bad:
            self.failures.append(f"unknown sponsor ids: {bad}")
        else:
            self.stdout.write(self.style.SUCCESS("sponsor       OK  every id is 1, 2, 3 or null"))

    def _shape(self, src):
        dupes = src.execute(
            "select count(*) from (select question_id from assessments_answerschema "
            "where question_id is not null group by 1 having count(*) > 1) d"
        ).fetchone()[0]
        if dupes:
            self.failures.append(
                f"{dupes} question(s) have more than one answer schema, but the target "
                f"models it as OneToOne")
        else:
            self.stdout.write(self.style.SUCCESS("onetoone      OK  one schema per question"))

    def _collisions(self, src):
        """Report exactly what legacy_load's resolution will decide.

        This used to partition the target with a fingerprint -- IMPORTED =
        "display_option = 'single_question'" -- and it was wrong twice over.

        It under-reported on a pristine target: the fingerprint is a property of
        the parent *survey*, so the genuine 2026 questions, schemas and options
        created inside imported survey 155 were counted as imported. That is the
        49-versus-58 gap.

        And it was destroyed by its own load: DISPLAY_OPTION_MAP rewrites
        single_question to by_question, so after one --apply the predicate
        matched nothing, every survey read as genuine, all 31,277 legacy ids
        read as collisions -- and the command still printed "preflight clean".

        So there is no fingerprint any more. This calls the same resolve() the
        loader calls, on the same witnesses, and reports what it returns. The
        two cannot disagree because there is only one implementation.
        """
        self.stdout.write("")
        with connection.cursor() as tgt:
            tgt.execute("select to_regclass(%s)", (RUN_MARKER,))
            if tgt.fetchone()[0]:
                tgt.execute(f"select applied_at from {RUN_MARKER} order by applied_at")
                when = ", ".join(str(r[0]) for r in tgt.fetchall())
                if when:
                    self.failures.append(
                        f"this target has already been loaded ({when}). legacy_load is "
                        f"one-shot, so there is nothing left for a preflight to inform -- "
                        f"restore from backup if you need to run it again.")
                    return

            self.stdout.write("resolution -- what legacy_load will do with each legacy row:")
            total = 0
            for name, lt, tt, witness_l, witness_t, stamped, resolver in RESOLVED:
                norm = (lambda w: tuple(_ms(v) for v in w)) if stamped else tuple
                lg = {r[0]: norm(r[1:]) for r in src.execute(
                    f"select id, {witness_l} from {lt}").fetchall()}
                tgt.execute(f"select id, {witness_t} from {tt}")
                tg = {r[0]: norm(r[1:]) for r in tgt.fetchall()}
                counter = iter(range(10 ** 9, 10 ** 9 + len(lg) + 1))
                r = resolver(name, lg, tg, lambda: next(counter))
                c = r.counts
                total += c[Mode.REMAP]
                self._row(lt, len(lg), c[Mode.UPDATE], c[Mode.INSERT], c[Mode.REMAP])

        self.stdout.write("")
        self.stdout.write(f"  {total} id(s) will be remapped and recorded in the "
                          f"legacy_id -> new_id map")

    def _row(self, name, legacy, update, insert, remap):
        style = self.style.WARNING if remap else (lambda s: s)
        self.stdout.write(
            f"  {name:<34}{legacy:>7} legacy  {update:>7} update  {insert:>6} insert  "
            + style(f"{remap:>4} remap"))

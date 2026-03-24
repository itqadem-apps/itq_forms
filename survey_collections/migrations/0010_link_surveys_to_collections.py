"""
Data migration: populate the SurveyCollection <-> Survey M2M from the legacy
GenericForeignKey (assessments.assessment.content_type/object_id -> blogs.blog).

Mapping extracted from assessment_exports/assessments_assessment.json and
assessment_exports/blogs_blog.json, keyed by collection title (since imported
collection PKs may differ from the original blog PKs).
"""

from django.db import migrations

# {collection_title: [survey_ids (old assessment pks)]}
COLLECTION_SURVEYS = {
    "منهج المهارات الأساسية للإستعداد للدمج": [23, 29, 30],
    "منهج دعم الدمج للصف الأول الإبتدائي": [6, 7, 8],
    "منهج دعم الدمج للصف الثاني الابتدائي": [26, 27, 28],
    "منهج دعم الدمج للصف الثالث الابتدائي": [24, 25, 72],
    "منهج مهارات تكنولوجيا التعلم": [31, 32, 33, 34],
    "منهج التأهيل المهني - فرصتي": [35, 36, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51],
    "منهج المهارات الحياتية والمنزلية": [9, 10, 11, 12, 14, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66],
    "منهج التقدم المتكامل للتوحد - المهارات الانتقالية": [77, 79, 80, 81, 82, 83, 84, 85, 86, 89],
    "منهج التوحد المتكامل - المهارات الحياتية": [90, 91, 92, 94, 95, 96, 97],
    "منهج التقدم المتكامل - المهارات المنزلية": [98, 99, 100, 101, 102, 103, 104, 105],
    "منهج التقدم المتكامل - مهارات الأداء المعرفي البصري": [106, 107, 108, 109, 110, 111, 112, 113, 114],
    "منهج التقدم المتكامل - الاستقلال الذاتي": [115, 116, 117, 118, 119, 120],
    "منهج التقدم المتكامل - مهارات الترويح و شغل وقت الفراغ": [121, 122, 123, 124, 125, 126, 127],
    "منهج التقدم المتكامل - مهارات التقليد الحركى": [128, 129, 130],
    "منهج التقدم المتكامل - مهارات اللعب": [131, 132, 133],
    "منهج التقدم المتكامل - مهارات اللغة المرتبطة بالمشاعر والانفعالات": [134, 135],
    "منهج التقدم المتكامل - المهارات الاجتماعية": [136],
    "منهج التقدم المتكامل - مهارات التواصل باستخدام الأجهزه الالكترونية - التابلت": [137],
    "منهج التقدم المتكامل - مهارات الصداقة": [138],
    "منهج التقدم المتكامل للتوحد - مهارات التقليد الصوتى": [140],
}


def link_surveys_to_collections(apps, schema_editor):
    SurveyCollectionTranslation = apps.get_model(
        "survey_collections", "SurveyCollectionTranslation"
    )
    Survey = apps.get_model("surveys", "Survey")

    for title, survey_ids in COLLECTION_SURVEYS.items():
        translation = SurveyCollectionTranslation.objects.filter(title=title).first()
        if not translation:
            continue
        collection = translation.collection
        existing_surveys = Survey.objects.filter(pk__in=survey_ids)
        collection.assessments.add(*existing_surveys)


def unlink_surveys_from_collections(apps, schema_editor):
    SurveyCollectionTranslation = apps.get_model(
        "survey_collections", "SurveyCollectionTranslation"
    )

    for title, survey_ids in COLLECTION_SURVEYS.items():
        translation = SurveyCollectionTranslation.objects.filter(title=title).first()
        if not translation:
            continue
        collection = translation.collection
        collection.assessments.remove(
            *collection.assessments.filter(pk__in=survey_ids)
        )


class Migration(migrations.Migration):

    dependencies = [
        ("survey_collections", "0009_remove_translatable_fields"),
        ("surveys", "0019_survey_lock_answers_survey_randomize_options_and_more"),
    ]

    operations = [
        migrations.RunPython(
            link_surveys_to_collections,
            unlink_surveys_from_collections,
        ),
    ]

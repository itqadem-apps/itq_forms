from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("user_surveys", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="UserAssessment",
            new_name="UserSurvey",
        ),
        migrations.RenameModel(
            old_name="UserAssessmentClassification",
            new_name="UserSurveyClassification",
        ),
        migrations.RenameModel(
            old_name="UserAssessmentRecommendation",
            new_name="UserSurveyRecommendation",
        ),
        migrations.RenameField(
            model_name="usersurveyclassification",
            old_name="user_assessment",
            new_name="user_survey",
        ),
        migrations.RenameField(
            model_name="usersurveyrecommendation",
            old_name="user_assessment",
            new_name="user_survey",
        ),
        migrations.RenameField(
            model_name="useranswer",
            old_name="user_assessment",
            new_name="user_survey",
        ),
        migrations.AlterField(
            model_name="usersurvey",
            name="classifications",
            field=models.ManyToManyField(
                through="user_surveys.UserSurveyClassification", to="surveys.classification"
            ),
        ),
        migrations.AlterField(
            model_name="usersurvey",
            name="recommendations",
            field=models.ManyToManyField(
                through="user_surveys.UserSurveyRecommendation", to="surveys.recommendation"
            ),
        ),
    ]

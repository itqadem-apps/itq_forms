from django.core.management.base import BaseCommand
from django.utils.timezone import now
from django.db.models import F

from user_surveys.models import UserSurvey
from user_surveys.services import finish_assessment


class Command(BaseCommand):
    help = "Auto-submit timed assessments that have exceeded their time limit."

    def handle(self, *args, **options):
        expired = UserSurvey.objects.filter(
            is_timed=True,
            time_limit__isnull=False,
            started_at__isnull=False,
            submitted_at__isnull=True,
        ).exclude(
            started_at__gt=now() - F("time_limit"),
        )

        count = 0
        for user_survey in expired:
            try:
                finish_assessment(user_survey, reason=UserSurvey.TERMINATION_TIME_EXPIRED)
                count += 1
            except Exception as e:
                self.stderr.write(f"Failed to auto-submit survey {user_survey.id}: {e}")

        self.stdout.write(f"Auto-submitted {count} expired assessment(s).")

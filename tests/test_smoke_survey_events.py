from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase

from surveys.messaging import build_survey_payload_or_log
from surveys.models import Survey


class SurveyEventsSmokeTest(TestCase):
    def test_published_survey_payload_has_org_uuid(self):
        org_id = uuid4()
        survey = Survey.objects.create(
            status=Survey.STATUS_PUBLISHED,
            organization_id=org_id,
        )

        payload = build_survey_payload_or_log(survey, "SurveyPublished")

        self.assertIsNotNone(payload)
        self.assertEqual(payload["organization_id"], str(org_id))

    def test_missing_org_uuid_skips_publishing_and_logs_reason(self):
        survey = Survey.objects.create(status=Survey.STATUS_PUBLISHED)

        with patch("app.messaging.publisher._outbox.add") as outbox_add:
            with self.assertLogs("surveys.messaging", level="WARNING") as logs:
                payload = build_survey_payload_or_log(survey, "SurveyPublished")

        self.assertIsNone(payload)
        outbox_add.assert_not_called()
        self.assertTrue(any("reason=missing_organization_id" in line for line in logs.output))
        self.assertTrue(any(f"survey_id={survey.pk}" in line for line in logs.output))

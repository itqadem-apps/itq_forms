from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase

from surveys.messaging import publish_assessment_status_event
from surveys.models import Survey


class AssessmentEventsSmokeTest(TestCase):
    def test_published_assessment_emits_event_with_org_uuid(self):
        org_id = uuid4()
        survey = Survey.objects.create(
            status=Survey.STATUS_PUBLISHED,
            organization_id=org_id,
        )

        with patch("surveys.messaging.event_bus.publish") as publish_mock:
            publish_assessment_status_event(survey)

        publish_mock.assert_called_once()
        event = publish_mock.call_args.args[0]
        self.assertEqual(event.event, "AssessmentPublished")
        self.assertEqual(event.organization_id, str(org_id))
        self.assertEqual(event.assessment["organization_id"], str(org_id))

    def test_missing_org_uuid_skips_publishing_and_logs_reason(self):
        survey = Survey.objects.create(status=Survey.STATUS_PUBLISHED)

        with patch("surveys.messaging.event_bus.publish") as publish_mock:
            with self.assertLogs("surveys.messaging", level="WARNING") as logs:
                publish_assessment_status_event(survey)

        publish_mock.assert_not_called()
        self.assertTrue(any("reason=missing_organization_id" in line for line in logs.output))
        self.assertTrue(any(f"assessment_id={survey.pk}" in line for line in logs.output))

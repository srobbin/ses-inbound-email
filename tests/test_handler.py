import json
import boto3
import pytest
import responses
from moto import mock_aws
from handler import lambda_handler
from event_helpers import make_s3_event, make_ses_notification_event


class TestLambdaHandler:
    @mock_aws
    @responses.activate
    def test_end_to_end_processes_email_and_sends_webhook(self, simple_html_email, domain_config, monkeypatch):
        # Set up S3
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="ses-incoming-emails")
        s3.create_bucket(Bucket="ses-email-attachments")
        s3.put_object(
            Bucket="ses-incoming-emails",
            Key="emails/abc123",
            Body=simple_html_email.encode(),
        )

        # Set up env
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        monkeypatch.setenv("ATTACHMENT_BUCKET", "ses-email-attachments")

        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        # Mock webhook endpoint
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        event = make_s3_event("ses-incoming-emails", "emails/abc123")
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200

        # Verify webhook was called
        assert len(responses.calls) == 1
        payload = json.loads(responses.calls[0].request.body)
        assert payload["event"] == "inbound"
        assert payload["sender"] == "sender@example.com"
        assert payload["recipient"] == "reply+123@letterclub.org"
        assert payload["subject"] == "Test Subject"
        assert payload["message-id"] == "<msg-002@example.com>"
        assert payload["in-reply-to"] == "<original@letterclub.org>"
        assert payload["references"] == "<original@letterclub.org>"
        assert "body-html" in payload
        assert "body-plain" in payload
        assert "stripped-html" in payload
        assert "stripped-text" in payload
        assert "attachments" in payload

    @mock_aws
    @responses.activate
    def test_processes_email_with_attachment(self, email_with_attachment, domain_config, monkeypatch):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="ses-incoming-emails")
        s3.create_bucket(Bucket="ses-email-attachments")
        s3.put_object(
            Bucket="ses-incoming-emails",
            Key="emails/att123",
            Body=email_with_attachment.encode(),
        )

        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        monkeypatch.setenv("ATTACHMENT_BUCKET", "ses-email-attachments")

        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        event = make_s3_event("ses-incoming-emails", "emails/att123")
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200

        payload = json.loads(responses.calls[0].request.body)
        assert len(payload["attachments"]) == 1
        assert payload["attachments"][0]["filename"] == "photo.png"
        assert payload["attachments"][0]["content-type"] == "image/png"
        assert "url" in payload["attachments"][0]
        assert "content" not in payload["attachments"][0]

    @responses.activate
    def test_routes_bounce_notification_to_webhook(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))

        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=200)

        bounce_notification = {
            "notificationType": "Bounce",
            "mail": {
                "source": "info@letterclub.org",
                "messageId": "bounce-001",
            },
            "bounce": {
                "bounceType": "Permanent",
                "bounceSubType": "General",
                "bouncedRecipients": [
                    {"emailAddress": "user@example.com", "diagnosticCode": "550 unknown"}
                ],
                "timestamp": "2026-04-12T12:00:00.000Z",
            },
        }
        event = make_ses_notification_event(bounce_notification)

        result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert len(responses.calls) == 1
        payload = json.loads(responses.calls[0].request.body)
        assert payload["event"] == "bounced"

    @mock_aws
    def test_discards_email_for_unknown_domain(self, monkeypatch):
        """Unknown domain returns 200 so SQS considers the message processed (no retries)."""
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="ses-incoming-emails")
        s3.create_bucket(Bucket="ses-email-attachments")

        from email.mime.text import MIMEText
        msg = MIMEText("Hello")
        msg["From"] = "sender@example.com"
        msg["To"] = "test@unknown-domain.com"
        msg["Subject"] = "Test"
        msg["Message-ID"] = "<msg@example.com>"

        s3.put_object(
            Bucket="ses-incoming-emails",
            Key="emails/unknown",
            Body=msg.as_string().encode(),
        )

        monkeypatch.setenv("DOMAIN_CONFIG", '{"letterclub.org": {"webhook_url": "https://letterclub.org/webhooks/inbound", "signing_secret": "secret"}}')
        monkeypatch.setenv("ATTACHMENT_BUCKET", "ses-email-attachments")

        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        event = make_s3_event("ses-incoming-emails", "emails/unknown")
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200

    @mock_aws
    @responses.activate
    def test_webhook_failure_raises_for_sqs_retry(self, simple_html_email, domain_config, monkeypatch):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="ses-incoming-emails")
        s3.create_bucket(Bucket="ses-email-attachments")
        s3.put_object(
            Bucket="ses-incoming-emails",
            Key="emails/retry123",
            Body=simple_html_email.encode(),
        )

        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        monkeypatch.setenv("ATTACHMENT_BUCKET", "ses-email-attachments")

        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        # Simulate webhook returning 503
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=503)

        from webhook_sender import WebhookDeliveryError

        event = make_s3_event("ses-incoming-emails", "emails/retry123")
        with pytest.raises(WebhookDeliveryError):
            lambda_handler(event, None)

    @responses.activate
    def test_routes_bounce_with_event_type_field(self, domain_config, monkeypatch):
        """Configuration Set event destinations use 'eventType' instead of 'notificationType'."""
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=200)

        bounce_notification = {
            "eventType": "Bounce",
            "mail": {
                "source": "info@letterclub.org",
                "messageId": "bounce-002",
            },
            "bounce": {
                "bounceType": "Permanent",
                "bounceSubType": "General",
                "bouncedRecipients": [
                    {"emailAddress": "user@example.com", "diagnosticCode": "550 unknown"}
                ],
                "timestamp": "2026-04-13T10:00:00.000Z",
            },
        }
        event = make_ses_notification_event(bounce_notification)
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        payload = json.loads(responses.calls[0].request.body)
        assert payload["event"] == "bounced"

    @responses.activate
    def test_routes_complaint_with_event_type_field(self, domain_config, monkeypatch):
        """Configuration Set event destinations use 'eventType' instead of 'notificationType'."""
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=200)

        complaint_notification = {
            "eventType": "Complaint",
            "mail": {
                "source": "info@letterclub.org",
                "messageId": "complaint-002",
            },
            "complaint": {
                "complainedRecipients": [
                    {"emailAddress": "user@example.com"}
                ],
                "complaintFeedbackType": "abuse",
                "timestamp": "2026-04-13T10:00:00.000Z",
            },
        }
        event = make_ses_notification_event(complaint_notification)
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        payload = json.loads(responses.calls[0].request.body)
        assert payload["event"] == "complained"

    def test_unknown_domain_bounce_is_discarded(self, monkeypatch):
        """Bounce for unconfigured domain returns success to avoid SQS retries."""
        monkeypatch.setenv("DOMAIN_CONFIG", '{"letterclub.org": {"webhook_url": "https://letterclub.org/webhooks/inbound", "signing_secret": "secret"}}')

        bounce_notification = {
            "notificationType": "Bounce",
            "mail": {
                "source": "info@unknown-domain.com",
                "messageId": "bounce-003",
            },
            "bounce": {
                "bounceType": "Permanent",
                "bounceSubType": "General",
                "bouncedRecipients": [
                    {"emailAddress": "user@example.com"}
                ],
                "timestamp": "2026-04-13T10:00:00.000Z",
            },
        }
        event = make_ses_notification_event(bounce_notification)
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200

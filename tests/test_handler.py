import json
import boto3
import pytest
import responses
from moto import mock_aws
from handler import lambda_handler


def make_sns_event(message_id):
    ses_notification = {
        "notificationType": "Received",
        "mail": {
            "messageId": message_id,
        },
        "receipt": {
            "action": {
                "type": "SNS",
                "topicArn": "arn:aws:sns:us-east-1:123456789:ses-inbound-email-notifications",
            }
        },
    }
    return {
        "Records": [
            {
                "Sns": {
                    "Message": json.dumps(ses_notification),
                }
            }
        ]
    }


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
        monkeypatch.setenv("INCOMING_EMAIL_BUCKET", "ses-incoming-emails")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        # Mock webhook endpoint
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        event = make_sns_event("abc123")
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200

        # Verify webhook was called
        assert len(responses.calls) == 1
        payload = json.loads(responses.calls[0].request.body)
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
        monkeypatch.setenv("INCOMING_EMAIL_BUCKET", "ses-incoming-emails")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        event = make_sns_event("att123")
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200

        payload = json.loads(responses.calls[0].request.body)
        assert len(payload["attachments"]) == 1
        assert payload["attachments"][0]["filename"] == "photo.png"
        assert payload["attachments"][0]["content-type"] == "image/png"
        assert "url" in payload["attachments"][0]
        assert "content" not in payload["attachments"][0]

    @mock_aws
    def test_returns_error_for_unknown_domain(self, monkeypatch):
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
        monkeypatch.setenv("INCOMING_EMAIL_BUCKET", "ses-incoming-emails")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        event = make_sns_event("unknown")
        result = lambda_handler(event, None)

        assert result["statusCode"] == 400

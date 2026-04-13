import json
import boto3
import pytest
import responses
from moto import mock_aws
from handler import lambda_handler
from event_helpers import make_s3_event


class TestHandlerForwarding:
    @mock_aws
    def test_forwards_email_when_recipient_matches_pattern(self, simple_text_email, monkeypatch):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="ses-incoming-emails")
        s3.create_bucket(Bucket="ses-email-attachments")

        # Build email to admin@letterclub.org
        from email.mime.text import MIMEText
        msg = MIMEText("Hello admin")
        msg["From"] = "someone@example.com"
        msg["To"] = "admin@letterclub.org"
        msg["Subject"] = "Admin inquiry"
        msg["Message-ID"] = "<admin-test@example.com>"

        s3.put_object(
            Bucket="ses-incoming-emails",
            Key="emails/admin-test",
            Body=msg.as_string().encode(),
        )

        # Verify the forwarding identity in SES (forwarder sends from info@<recipient-domain>)
        ses = boto3.client("ses", region_name="us-east-1")
        ses.verify_email_identity(EmailAddress="info@letterclub.org")

        domain_config = {
            "letterclub.org": {
                "webhook_url": "https://letterclub.org/webhooks/inbound",
                "signing_secret": "secret",
                "forwards": {
                    "admin|support": "scott@robbin.co"
                }
            }
        }
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        monkeypatch.setenv("ATTACHMENT_BUCKET", "ses-email-attachments")

        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        event = make_s3_event("ses-incoming-emails", "emails/admin-test")
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert "Forwarded" in result["body"]

    @mock_aws
    @responses.activate
    def test_does_not_forward_when_no_pattern_matches(self, monkeypatch):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="ses-incoming-emails")
        s3.create_bucket(Bucket="ses-email-attachments")

        from email.mime.text import MIMEText
        msg = MIMEText("A contribution")
        msg["From"] = "user@example.com"
        msg["To"] = "reply+123@letterclub.org"
        msg["Subject"] = "My reply"
        msg["Message-ID"] = "<reply-test@example.com>"

        s3.put_object(
            Bucket="ses-incoming-emails",
            Key="emails/reply-test",
            Body=msg.as_string().encode(),
        )

        domain_config = {
            "letterclub.org": {
                "webhook_url": "https://letterclub.org/webhooks/inbound",
                "signing_secret": "secret",
                "forwards": {
                    "admin|support": "scott@robbin.co"
                }
            }
        }
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        monkeypatch.setenv("ATTACHMENT_BUCKET", "ses-email-attachments")

        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        event = make_s3_event("ses-incoming-emails", "emails/reply-test")
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert result["body"] == "OK"
        assert len(responses.calls) == 1  # webhook was called

    @mock_aws
    @responses.activate
    def test_no_forwards_config_sends_webhook(self, monkeypatch):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="ses-incoming-emails")
        s3.create_bucket(Bucket="ses-email-attachments")

        from email.mime.text import MIMEText
        msg = MIMEText("Hello")
        msg["From"] = "user@example.com"
        msg["To"] = "admin@noforward.com"
        msg["Subject"] = "Test"
        msg["Message-ID"] = "<nf-test@example.com>"

        s3.put_object(
            Bucket="ses-incoming-emails",
            Key="emails/nf-test",
            Body=msg.as_string().encode(),
        )

        domain_config = {
            "noforward.com": {
                "webhook_url": "https://noforward.com/webhooks/inbound",
                "signing_secret": "secret"
            }
        }
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        monkeypatch.setenv("ATTACHMENT_BUCKET", "ses-email-attachments")

        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        responses.add(responses.POST, "https://noforward.com/webhooks/inbound", status=201)

        event = make_s3_event("ses-incoming-emails", "emails/nf-test")
        result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert result["body"] == "OK"
        assert len(responses.calls) == 1

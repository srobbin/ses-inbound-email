import json
import pytest
import responses
from notification_handler import handle_bounce, handle_complaint


def make_bounce_message(source="info@letterclub.org", recipients=None, bounce_type="Permanent", bounce_subtype="General"):
    if recipients is None:
        recipients = [{"emailAddress": "user@example.com", "diagnosticCode": "smtp; 550 5.1.1 user unknown"}]
    return {
        "notificationType": "Bounce",
        "mail": {
            "source": source,
            "messageId": "bounce-msg-001",
        },
        "bounce": {
            "bounceType": bounce_type,
            "bounceSubType": bounce_subtype,
            "bouncedRecipients": recipients,
            "timestamp": "2026-04-12T12:32:36.000Z",
        },
    }


def make_complaint_message(source="info@letterclub.org", recipients=None, feedback_type="abuse"):
    if recipients is None:
        recipients = [{"emailAddress": "user@example.com"}]
    return {
        "notificationType": "Complaint",
        "mail": {
            "source": source,
            "messageId": "complaint-msg-001",
        },
        "complaint": {
            "complainedRecipients": recipients,
            "complaintFeedbackType": feedback_type,
            "timestamp": "2026-04-12T14:00:00.000Z",
        },
    }


class TestHandleBounce:
    @responses.activate
    def test_sends_bounce_webhook(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=200)

        result = handle_bounce(make_bounce_message())

        assert result["statusCode"] == 200
        assert len(responses.calls) == 1

        payload = json.loads(responses.calls[0].request.body)
        assert payload["event"] == "bounced"
        assert payload["recipient"] == "user@example.com"
        assert payload["sender"] == "info@letterclub.org"
        assert payload["bounce_type"] == "Permanent"
        assert payload["bounce_subtype"] == "General"
        assert payload["diagnostic"] == "smtp; 550 5.1.1 user unknown"
        assert payload["timestamp"] == "2026-04-12T12:32:36.000Z"

    @responses.activate
    def test_sends_webhook_per_recipient(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=200)

        recipients = [
            {"emailAddress": "user1@example.com", "diagnosticCode": "550 unknown"},
            {"emailAddress": "user2@example.com", "diagnosticCode": "552 full"},
        ]
        result = handle_bounce(make_bounce_message(recipients=recipients))

        assert result["statusCode"] == 200
        assert len(responses.calls) == 2

        payload1 = json.loads(responses.calls[0].request.body)
        payload2 = json.loads(responses.calls[1].request.body)
        assert payload1["recipient"] == "user1@example.com"
        assert payload2["recipient"] == "user2@example.com"

    @responses.activate
    def test_handles_missing_diagnostic_code(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=200)

        recipients = [{"emailAddress": "user@example.com"}]
        result = handle_bounce(make_bounce_message(recipients=recipients))

        assert result["statusCode"] == 200
        payload = json.loads(responses.calls[0].request.body)
        assert payload["diagnostic"] == ""

    @responses.activate
    def test_routes_to_correct_domain_webhook(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        responses.add(responses.POST, "https://other-app.com/webhooks/inbound", status=200)

        result = handle_bounce(make_bounce_message(source="info@other-app.com"))

        assert result["statusCode"] == 200
        assert len(responses.calls) == 1
        assert responses.calls[0].request.url == "https://other-app.com/webhooks/inbound"


class TestHandleComplaint:
    @responses.activate
    def test_sends_complaint_webhook(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=200)

        result = handle_complaint(make_complaint_message())

        assert result["statusCode"] == 200
        assert len(responses.calls) == 1

        payload = json.loads(responses.calls[0].request.body)
        assert payload["event"] == "complained"
        assert payload["recipient"] == "user@example.com"
        assert payload["sender"] == "info@letterclub.org"
        assert payload["complaint_type"] == "abuse"
        assert payload["timestamp"] == "2026-04-12T14:00:00.000Z"

    @responses.activate
    def test_handles_missing_feedback_type(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=200)

        msg = make_complaint_message()
        del msg["complaint"]["complaintFeedbackType"]
        result = handle_complaint(msg)

        assert result["statusCode"] == 200
        payload = json.loads(responses.calls[0].request.body)
        assert payload["complaint_type"] == ""

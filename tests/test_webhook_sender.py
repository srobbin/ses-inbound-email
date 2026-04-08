import hashlib
import hmac
import json
import time
import pytest
import responses
from src.webhook_sender import send_webhook, WebhookDeliveryError


class TestSendWebhook:
    @responses.activate
    def test_posts_payload_to_webhook_url(self):
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        payload = {"sender": "user@example.com", "subject": "Test"}
        send_webhook("https://letterclub.org/webhooks/inbound", payload, "secret-key")

        assert len(responses.calls) == 1
        assert responses.calls[0].request.url == "https://letterclub.org/webhooks/inbound"

    @responses.activate
    def test_sends_json_content_type(self):
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        payload = {"sender": "user@example.com"}
        send_webhook("https://letterclub.org/webhooks/inbound", payload, "secret-key")

        assert responses.calls[0].request.headers["Content-Type"] == "application/json"

    @responses.activate
    def test_sends_hmac_signature_header(self):
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        payload = {"sender": "user@example.com"}
        send_webhook("https://letterclub.org/webhooks/inbound", payload, "secret-key")

        request = responses.calls[0].request
        assert "X-Signature" in request.headers
        assert "X-Timestamp" in request.headers

    @responses.activate
    def test_signature_is_valid_hmac(self):
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        payload = {"sender": "user@example.com"}
        secret = "my-secret"
        send_webhook("https://letterclub.org/webhooks/inbound", payload, secret)

        request = responses.calls[0].request
        timestamp = request.headers["X-Timestamp"]
        body = request.body
        expected_sig = hmac.new(
            secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256
        ).hexdigest()

        assert request.headers["X-Signature"] == expected_sig

    @responses.activate
    def test_timestamp_is_recent(self):
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        payload = {"sender": "user@example.com"}
        send_webhook("https://letterclub.org/webhooks/inbound", payload, "secret")

        timestamp = int(responses.calls[0].request.headers["X-Timestamp"])
        assert abs(time.time() - timestamp) < 5

    @responses.activate
    def test_raises_on_non_2xx_response(self):
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=500)

        payload = {"sender": "user@example.com"}

        with pytest.raises(WebhookDeliveryError):
            send_webhook("https://letterclub.org/webhooks/inbound", payload, "secret")

    @responses.activate
    def test_payload_is_valid_json(self):
        responses.add(responses.POST, "https://letterclub.org/webhooks/inbound", status=201)

        payload = {"sender": "user@example.com", "subject": "Test"}
        send_webhook("https://letterclub.org/webhooks/inbound", payload, "secret")

        body = responses.calls[0].request.body
        parsed = json.loads(body)
        assert parsed["sender"] == "user@example.com"
        assert parsed["subject"] == "Test"

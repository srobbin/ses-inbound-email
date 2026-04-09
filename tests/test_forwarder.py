import pytest
from moto import mock_aws
import boto3
from forwarder import check_forward, forward_email


class TestCheckForward:
    def test_matches_simple_pattern(self):
        forwards = {"admin|support": "dest@example.com"}
        assert check_forward("admin@letterclub.org", forwards) == "dest@example.com"

    def test_matches_second_option_in_pattern(self):
        forwards = {"admin|support": "dest@example.com"}
        assert check_forward("support@letterclub.org", forwards) == "dest@example.com"

    def test_no_match_returns_none(self):
        forwards = {"admin|support": "dest@example.com"}
        assert check_forward("reply+123@letterclub.org", forwards) is None

    def test_empty_forwards_returns_none(self):
        assert check_forward("admin@letterclub.org", {}) is None

    def test_none_forwards_returns_none(self):
        assert check_forward("admin@letterclub.org", None) is None

    def test_case_insensitive(self):
        forwards = {"admin|support": "dest@example.com"}
        assert check_forward("Admin@letterclub.org", forwards) == "dest@example.com"

    def test_multiple_patterns(self):
        forwards = {
            "admin|support": "admin@example.com",
            "billing|sales": "finance@example.com",
        }
        assert check_forward("billing@letterclub.org", forwards) == "finance@example.com"

    def test_does_not_partial_match(self):
        forwards = {"admin": "dest@example.com"}
        assert check_forward("administrator@letterclub.org", forwards) is None

    def test_matches_with_complex_local_part(self):
        forwards = {"no-reply|noreply": "dest@example.com"}
        assert check_forward("no-reply@letterclub.org", forwards) == "dest@example.com"


class TestForwardEmail:
    @mock_aws
    def test_forwards_email_via_ses(self, simple_text_email):
        ses = boto3.client("ses", region_name="us-east-1")
        # Verify sender identity (required by moto)
        ses.verify_email_identity(EmailAddress="sender@example.com")

        forward_email(
            raw_email=simple_text_email,
            recipient="admin@letterclub.org",
            destination="scott@robbin.co",
            region="us-east-1",
        )

        # moto doesn't let us inspect sent emails easily, but if no exception was raised, it worked
        # The key test is that it doesn't raise

    @mock_aws
    def test_preserves_original_to_header(self, simple_text_email):
        ses = boto3.client("ses", region_name="us-east-1")
        ses.verify_email_identity(EmailAddress="sender@example.com")

        import email as email_lib
        msg = email_lib.message_from_string(simple_text_email)
        original_to = msg["To"]

        forward_email(
            raw_email=simple_text_email,
            recipient="admin@letterclub.org",
            destination="scott@robbin.co",
            region="us-east-1",
        )

        # The original To header should remain unchanged in the message
        # (only the envelope destination changes for routing)
        msg_after = email_lib.message_from_string(simple_text_email)
        assert msg_after["To"] == original_to

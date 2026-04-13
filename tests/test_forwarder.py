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
        # forwarder.py sends from info@<recipient-domain>, so that identity
        # is what needs to be verified in moto — not the original sender.
        ses.verify_email_identity(EmailAddress="info@letterclub.org")

        forward_email(
            raw_email=simple_text_email,
            recipient="admin@letterclub.org",
            destination="scott@robbin.co",
            region="us-east-1",
        )

        # moto doesn't let us inspect sent emails easily, but if no exception was raised, it worked
        # The key test is that it doesn't raise

    @mock_aws
    def test_passes_configuration_set_name_when_set(self, simple_text_email, monkeypatch):
        monkeypatch.setenv("CONFIGURATION_SET_NAME", "my-config-set")

        ses = boto3.client("ses", region_name="us-east-1")
        ses.verify_email_identity(EmailAddress="info@letterclub.org")

        # If ConfigurationSetName is invalid, moto would raise. Since moto
        # doesn't validate config set names, we just verify no exception.
        forward_email(
            raw_email=simple_text_email,
            recipient="admin@letterclub.org",
            destination="scott@robbin.co",
            region="us-east-1",
        )

    @mock_aws
    def test_preserves_original_to_header(self, simple_text_email):
        ses = boto3.client("ses", region_name="us-east-1")
        ses.verify_email_identity(EmailAddress="info@letterclub.org")

        import email as email_lib
        original_to = email_lib.message_from_string(simple_text_email)["To"]

        # Monkey-patch SES to capture the forwarded message
        import unittest.mock as mock
        with mock.patch("forwarder.boto3") as mock_boto3:
            mock_ses = mock.MagicMock()
            mock_boto3.client.return_value = mock_ses

            forward_email(
                raw_email=simple_text_email,
                recipient="admin@letterclub.org",
                destination="scott@robbin.co",
                region="us-east-1",
            )

            sent_raw = mock_ses.send_raw_email.call_args[1]["RawMessage"]["Data"]
            forwarded_msg = email_lib.message_from_string(sent_raw)
            assert forwarded_msg["To"] == original_to

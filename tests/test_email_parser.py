import pytest
from src.email_parser import parse_email


class TestParseEmail:
    def test_extracts_headers_from_text_email(self, simple_text_email):
        result = parse_email(simple_text_email)

        assert result["sender"] == "sender@example.com"
        assert result["recipient"] == "reply+123@letterclub.org"
        assert result["subject"] == "Test Subject"
        assert result["message-id"] == "<msg-001@example.com>"

    def test_extracts_body_plain_from_text_email(self, simple_text_email):
        result = parse_email(simple_text_email)

        assert result["body-plain"] == "Hello, this is a test email."
        assert result["body-html"] is None

    def test_extracts_html_and_text_from_multipart(self, simple_html_email):
        result = parse_email(simple_html_email)

        assert result["body-plain"] == "Hello, this is a test."
        assert "<b>test</b>" in result["body-html"]

    def test_extracts_threading_headers(self, simple_html_email):
        result = parse_email(simple_html_email)

        assert result["in-reply-to"] == "<original@letterclub.org>"
        assert result["references"] == "<original@letterclub.org>"

    def test_missing_threading_headers_are_none(self, simple_text_email):
        result = parse_email(simple_text_email)

        assert result["in-reply-to"] is None
        assert result["references"] is None

    def test_extracts_domain_from_recipient(self, simple_text_email):
        result = parse_email(simple_text_email)

        assert result["domain"] == "letterclub.org"

    def test_extracts_attachments_metadata(self, email_with_attachment):
        result = parse_email(email_with_attachment)

        assert len(result["attachments"]) == 1
        att = result["attachments"][0]
        assert att["filename"] == "photo.png"
        assert att["content-type"] == "image/png"
        assert isinstance(att["content"], bytes)
        assert len(att["content"]) > 0

    def test_extracts_inline_images(self, email_with_inline_image):
        result = parse_email(email_with_inline_image)

        assert len(result["attachments"]) == 1
        att = result["attachments"][0]
        assert att["content-id"] == "<img001>"
        assert att["filename"] == "inline.png"
        assert att["content-type"] == "image/png"

    def test_text_only_email_has_empty_attachments(self, simple_text_email):
        result = parse_email(simple_text_email)

        assert result["attachments"] == []

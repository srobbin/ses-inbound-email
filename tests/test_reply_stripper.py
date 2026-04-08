import pytest
from src.reply_stripper import strip_reply


class TestStripReply:
    def test_strips_quoted_text_from_plain_text(self):
        text = "This is my reply.\n\nOn Jan 1, 2026, someone wrote:\n> Original message."

        result = strip_reply(text=text, html=None)

        assert "This is my reply." in result["stripped-text"]
        assert "Original message" not in result["stripped-text"]

    def test_strips_quoted_html(self):
        html = (
            "<div>This is my reply.</div>"
            '<div class="gmail_quote">'
            "<p>On Jan 1, 2026, someone wrote:</p>"
            "<blockquote>Original message.</blockquote>"
            "</div>"
        )

        result = strip_reply(text=None, html=html)

        assert "my reply" in result["stripped-html"]
        assert "Original message" not in result["stripped-html"]

    def test_returns_full_text_when_no_quote_found(self):
        text = "Just a simple message with no quotes."

        result = strip_reply(text=text, html=None)

        assert result["stripped-text"] == text

    def test_returns_full_html_when_no_quote_found(self):
        html = "<p>Just a simple message.</p>"

        result = strip_reply(text=None, html=html)

        assert result["stripped-html"] == html

    def test_handles_none_inputs(self):
        result = strip_reply(text=None, html=None)

        assert result["stripped-text"] is None
        assert result["stripped-html"] is None

    def test_handles_both_text_and_html(self):
        text = "My reply.\n\nOn Jan 1, 2026, someone wrote:\n> Original."
        html = (
            "<div>My reply.</div>"
            '<div class="gmail_quote">'
            "<blockquote>Original.</blockquote>"
            "</div>"
        )

        result = strip_reply(text=text, html=html)

        assert "My reply" in result["stripped-text"]
        assert "Original" not in result["stripped-text"]
        assert "My reply" in result["stripped-html"]
        assert "Original" not in result["stripped-html"]

    def test_preserves_full_text_when_quote_format_not_recognized(self):
        # quotequail does not recognize short date formats like "On Jan 1:" (without year),
        # so the full text is returned unchanged.
        text = "Reply text.\n\nOn Jan 1:\n> Quoted text."

        result = strip_reply(text=text, html=None)

        assert result["stripped-text"] == text

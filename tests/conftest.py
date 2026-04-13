import sys
from pathlib import Path

# Add src/ and tests/ to path so imports work the same as in Lambda
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_cached_clients():
    """Reset module-level boto3 client caches so each moto test gets a fresh client."""
    import handler
    import attachment_handler
    handler._s3_client = None
    attachment_handler._s3_client = None
    yield
    handler._s3_client = None
    attachment_handler._s3_client = None


@pytest.fixture
def simple_text_email():
    msg = MIMEText("Hello, this is a test email.", "plain")
    msg["From"] = "sender@example.com"
    msg["To"] = "reply+123@letterclub.org"
    msg["Subject"] = "Test Subject"
    msg["Message-ID"] = "<msg-001@example.com>"
    return msg.as_string()


@pytest.fixture
def simple_html_email():
    msg = MIMEMultipart("alternative")
    msg["From"] = "sender@example.com"
    msg["To"] = "reply+123@letterclub.org"
    msg["Subject"] = "Test Subject"
    msg["Message-ID"] = "<msg-002@example.com>"
    msg["In-Reply-To"] = "<original@letterclub.org>"
    msg["References"] = "<original@letterclub.org>"

    text_part = MIMEText("Hello, this is a test.", "plain")
    html_part = MIMEText("<p>Hello, this is a <b>test</b>.</p>", "html")
    msg.attach(text_part)
    msg.attach(html_part)
    return msg.as_string()


@pytest.fixture
def email_with_reply():
    msg = MIMEMultipart("alternative")
    msg["From"] = "sender@example.com"
    msg["To"] = "reply+456@letterclub.org"
    msg["Subject"] = "Re: Original Subject"
    msg["Message-ID"] = "<msg-003@example.com>"
    msg["In-Reply-To"] = "<original@letterclub.org>"
    msg["References"] = "<original@letterclub.org>"

    text_body = "This is my reply.\n\nOn Jan 1, 2026, someone wrote:\n> This is the original message."
    html_body = (
        "<div>This is my reply.</div>"
        '<div class="gmail_quote">'
        "<p>On Jan 1, 2026, someone wrote:</p>"
        "<blockquote>This is the original message.</blockquote>"
        "</div>"
    )

    text_part = MIMEText(text_body, "plain")
    html_part = MIMEText(html_body, "html")
    msg.attach(text_part)
    msg.attach(html_part)
    return msg.as_string()


@pytest.fixture
def email_with_attachment():
    msg = MIMEMultipart("mixed")
    msg["From"] = "sender@example.com"
    msg["To"] = "reply+789@letterclub.org"
    msg["Subject"] = "With Attachment"
    msg["Message-ID"] = "<msg-004@example.com>"

    text_part = MIMEText("See attached image.", "plain")
    msg.attach(text_part)

    # Small 1x1 red PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
        b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
        b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    image_part = MIMEImage(png_bytes, "png", name="photo.png")
    image_part.add_header("Content-Disposition", "attachment", filename="photo.png")
    msg.attach(image_part)

    return msg.as_string()


@pytest.fixture
def email_with_inline_image():
    msg = MIMEMultipart("related")
    msg["From"] = "sender@example.com"
    msg["To"] = "reply+101@letterclub.org"
    msg["Subject"] = "Inline Image"
    msg["Message-ID"] = "<msg-005@example.com>"

    html_body = '<p>Check this out:</p><img src="cid:img001">'
    html_part = MIMEText(html_body, "html")
    msg.attach(html_part)

    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
        b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
        b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    image_part = MIMEImage(png_bytes, "png")
    image_part.add_header("Content-ID", "<img001>")
    image_part.add_header("Content-Disposition", "inline", filename="inline.png")
    msg.attach(image_part)

    return msg.as_string()


@pytest.fixture
def domain_config():
    return {
        "letterclub.org": {
            "webhook_url": "https://letterclub.org/webhooks/inbound",
            "signing_secret": "test-secret-key"
        },
        "other-app.com": {
            "webhook_url": "https://other-app.com/webhooks/inbound",
            "signing_secret": "other-secret-key"
        }
    }

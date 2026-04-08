# SES Inbound Email Lambda — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable Python Lambda that receives raw emails from SES, parses them, strips quoted replies, and POSTs a clean JSON payload to a configured webhook URL.

**Architecture:** SES stores raw inbound email in S3 and notifies SNS. SNS triggers the Lambda, which parses the MIME message, strips quoted replies with `quotequail`, extracts attachments (uploads them to S3 with signed URLs), looks up the webhook URL from domain config, and POSTs a signed JSON payload. AWS SAM manages all infrastructure.

**Tech Stack:** Python 3.13, AWS SAM, boto3, quotequail, pytest, moto (S3 mocking)

**Spec:** See `/Users/srobbin/Git/letter-club/docs/superpowers/specs/2026-04-08-mailgun-to-ses-migration-design.md` (Part 1)

**Webhook contract (consumed by Rails app):**
- POST to configured webhook URL
- Headers: `X-Signature` (HMAC-SHA256 of `{timestamp}.{body}`), `X-Timestamp` (Unix epoch string), `Content-Type: application/json`
- Body: JSON payload (see spec for full schema)

---

## File Structure

### Files to create

```
ses-inbound-email/
├── template.yaml                    # SAM template (Lambda, S3, SNS, IAM)
├── src/
│   ├── handler.py                   # Lambda entry point
│   ├── email_parser.py              # MIME parsing, header extraction
│   ├── reply_stripper.py            # quotequail wrapper for HTML/text stripping
│   ├── attachment_handler.py        # Extract attachments, upload to S3, signed URLs
│   ├── webhook_sender.py            # POST payload with HMAC signature
│   └── config.py                    # Domain config lookup from env var
├── requirements.txt                 # quotequail, requests
├── tests/
│   ├── conftest.py                  # Shared fixtures (sample emails, mock AWS)
│   ├── test_email_parser.py
│   ├── test_reply_stripper.py
│   ├── test_attachment_handler.py
│   ├── test_webhook_sender.py
│   ├── test_config.py
│   ├── test_handler.py              # Integration test
│   └── fixtures/
│       ├── simple_text.eml          # Plain text email
│       ├── simple_html.eml          # HTML email
│       ├── with_reply.eml           # Email with quoted reply
│       ├── with_attachment.eml      # Email with image attachment
│       └── with_inline_image.eml    # Email with inline CID image
├── .gitignore
└── README.md
```

---

## Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `tests/conftest.py`
- Create: `.gitignore`
- Create: `src/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)

- [ ] **Step 1: Create `.gitignore`**

Create `.gitignore`:

```
__pycache__/
*.pyc
.pytest_cache/
.aws-sam/
.venv/
*.egg-info/
dist/
build/
```

- [ ] **Step 2: Create `requirements.txt`**

```
quotequail>=0.3.0
requests>=2.31.0
```

- [ ] **Step 3: Create a dev requirements file**

Create `requirements-dev.txt`:

```
-r requirements.txt
pytest>=8.0.0
moto[s3]>=5.0.0
responses>=0.25.0
```

- [ ] **Step 4: Create empty `__init__.py` files**

Create `src/__init__.py` (empty file) and `tests/__init__.py` (empty file).

- [ ] **Step 5: Create `tests/conftest.py` with shared fixtures**

```python
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from pathlib import Path
import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
```

- [ ] **Step 6: Set up virtual environment and install dependencies**

```bash
cd /Users/srobbin/Git/ses-inbound-email
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

- [ ] **Step 7: Verify pytest runs (no tests yet)**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/ -v`
Expected: "no tests ran" / 0 collected

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: project scaffolding with dependencies and test fixtures"
```

---

## Task 2: Domain config lookup

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_config.py`:

```python
import json
import os
import pytest
from src.config import get_domain_config, DomainNotConfiguredError


class TestGetDomainConfig:
    def test_returns_config_for_known_domain(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))

        result = get_domain_config("letterclub.org")

        assert result["webhook_url"] == "https://letterclub.org/webhooks/inbound"
        assert result["signing_secret"] == "test-secret-key"

    def test_returns_config_for_different_domain(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))

        result = get_domain_config("other-app.com")

        assert result["webhook_url"] == "https://other-app.com/webhooks/inbound"

    def test_raises_for_unknown_domain(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))

        with pytest.raises(DomainNotConfiguredError, match="unknown.com"):
            get_domain_config("unknown.com")

    def test_raises_when_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("DOMAIN_CONFIG", raising=False)

        with pytest.raises(DomainNotConfiguredError):
            get_domain_config("letterclub.org")

    def test_raises_when_env_var_is_invalid_json(self, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", "not-json")

        with pytest.raises(DomainNotConfiguredError):
            get_domain_config("letterclub.org")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `src.config` module doesn't exist

- [ ] **Step 3: Write implementation**

Create `src/config.py`:

```python
import json
import os


class DomainNotConfiguredError(Exception):
    pass


def get_domain_config(domain: str) -> dict:
    raw = os.environ.get("DOMAIN_CONFIG")
    if not raw:
        raise DomainNotConfiguredError(f"DOMAIN_CONFIG env var not set, cannot look up {domain}")

    try:
        config = json.loads(raw)
    except json.JSONDecodeError:
        raise DomainNotConfiguredError(f"DOMAIN_CONFIG is not valid JSON, cannot look up {domain}")

    if domain not in config:
        raise DomainNotConfiguredError(f"No config found for domain: {domain}")

    return config[domain]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_config.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: domain config lookup from env var"
```

---

## Task 3: Email parser

**Files:**
- Create: `src/email_parser.py`
- Create: `tests/test_email_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_email_parser.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_email_parser.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Write implementation**

Create `src/email_parser.py`:

```python
import email
from email import policy
from email.utils import parseaddr


def parse_email(raw_email: str) -> dict:
    msg = email.message_from_string(raw_email, policy=policy.default)

    sender = parseaddr(msg["From"])[1]
    recipient = parseaddr(msg["To"])[1]
    domain = recipient.split("@")[1] if "@" in recipient else None

    body_plain = None
    body_html = None
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            content_id = part.get("Content-ID")

            # Inline or attached images/files
            if part.get_content_maintype() == "image" or "attachment" in content_disposition:
                if part.get_content_maintype() == "image":
                    payload = part.get_payload(decode=True)
                    if payload:
                        filename = part.get_filename() or "attachment"
                        att = {
                            "filename": filename,
                            "content-type": content_type,
                            "content": payload,
                        }
                        if content_id:
                            att["content-id"] = content_id
                        attachments.append(att)
                continue

            if content_type == "text/plain" and body_plain is None:
                body_plain = part.get_content()
            elif content_type == "text/html" and body_html is None:
                body_html = part.get_content()
    else:
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            body_plain = msg.get_content()
        elif content_type == "text/html":
            body_html = msg.get_content()

    return {
        "sender": sender,
        "recipient": recipient,
        "domain": domain,
        "subject": msg["Subject"],
        "message-id": msg["Message-ID"],
        "in-reply-to": msg.get("In-Reply-To"),
        "references": msg.get("References"),
        "body-plain": body_plain,
        "body-html": body_html,
        "attachments": attachments,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_email_parser.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/email_parser.py tests/test_email_parser.py
git commit -m "feat: MIME email parser with header and attachment extraction"
```

---

## Task 4: Reply stripper

**Files:**
- Create: `src/reply_stripper.py`
- Create: `tests/test_reply_stripper.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_reply_stripper.py`:

```python
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

    def test_preserves_full_versions(self, email_with_reply):
        """The strip function only returns stripped versions;
        full versions are preserved by the caller."""
        text = "Reply text.\n\nOn Jan 1:\n> Quoted text."

        result = strip_reply(text=text, html=None)

        # Stripped version should not contain quoted text
        assert "Quoted text" not in result["stripped-text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_reply_stripper.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Write implementation**

Create `src/reply_stripper.py`:

```python
import quotequail


def strip_reply(text: str | None, html: str | None) -> dict:
    stripped_text = _strip_text(text) if text else None
    stripped_html = _strip_html(html) if html else None

    return {
        "stripped-text": stripped_text,
        "stripped-html": stripped_html,
    }


def _strip_text(text: str) -> str:
    result = quotequail.unwrap_plain(text)
    if result and result.get("text_top"):
        return result["text_top"].strip()
    return text


def _strip_html(html: str) -> str:
    result = quotequail.unwrap_html(html)
    if result and result.get("html_top"):
        return result["html_top"].strip()
    return html
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_reply_stripper.py -v`
Expected: PASS (7 tests). Some stripping tests may need adjustment depending on quotequail's exact output — if a test fails because quotequail strips differently than expected, update the assertion to match actual behavior (the library's behavior is the source of truth).

- [ ] **Step 5: Commit**

```bash
git add src/reply_stripper.py tests/test_reply_stripper.py
git commit -m "feat: reply stripper with quotequail for HTML and plain text"
```

---

## Task 5: Attachment handler

**Files:**
- Create: `src/attachment_handler.py`
- Create: `tests/test_attachment_handler.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_attachment_handler.py`:

```python
import boto3
import pytest
from moto import mock_aws
from src.attachment_handler import upload_attachments


@pytest.fixture
def s3_bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket_name = "test-email-attachments"
        s3.create_bucket(Bucket=bucket_name)
        yield bucket_name


class TestUploadAttachments:
    def test_uploads_attachment_to_s3_and_returns_signed_url(self, s3_bucket):
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=s3_bucket)

            attachments = [
                {
                    "filename": "photo.png",
                    "content-type": "image/png",
                    "content": b"\x89PNG fake image data",
                }
            ]

            result = upload_attachments(attachments, s3_bucket, "us-east-1")

            assert len(result) == 1
            assert result[0]["filename"] == "photo.png"
            assert result[0]["content-type"] == "image/png"
            assert "url" in result[0]
            assert s3_bucket in result[0]["url"]
            # Should not contain raw content
            assert "content" not in result[0]

    def test_uploads_multiple_attachments(self, s3_bucket):
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=s3_bucket)

            attachments = [
                {
                    "filename": "photo1.png",
                    "content-type": "image/png",
                    "content": b"image1",
                },
                {
                    "filename": "photo2.jpg",
                    "content-type": "image/jpeg",
                    "content": b"image2",
                },
            ]

            result = upload_attachments(attachments, s3_bucket, "us-east-1")

            assert len(result) == 2
            assert result[0]["filename"] == "photo1.png"
            assert result[1]["filename"] == "photo2.jpg"

    def test_returns_empty_list_for_no_attachments(self, s3_bucket):
        with mock_aws():
            result = upload_attachments([], s3_bucket, "us-east-1")

            assert result == []

    def test_preserves_content_id_for_inline_images(self, s3_bucket):
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=s3_bucket)

            attachments = [
                {
                    "filename": "inline.png",
                    "content-type": "image/png",
                    "content": b"inline image",
                    "content-id": "<img001>",
                }
            ]

            result = upload_attachments(attachments, s3_bucket, "us-east-1")

            assert result[0]["content-id"] == "<img001>"

    def test_s3_key_includes_unique_prefix(self, s3_bucket):
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=s3_bucket)

            attachments = [
                {
                    "filename": "photo.png",
                    "content-type": "image/png",
                    "content": b"data",
                }
            ]

            result = upload_attachments(attachments, s3_bucket, "us-east-1")

            # URL should contain the filename
            assert "photo.png" in result[0]["url"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_attachment_handler.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Write implementation**

Create `src/attachment_handler.py`:

```python
import uuid
import boto3
from botocore.config import Config


def upload_attachments(attachments: list[dict], bucket: str, region: str) -> list[dict]:
    if not attachments:
        return []

    s3 = boto3.client("s3", region_name=region, config=Config(signature_version="s3v4"))
    results = []

    for attachment in attachments:
        key = f"attachments/{uuid.uuid4()}/{attachment['filename']}"

        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=attachment["content"],
            ContentType=attachment["content-type"],
        )

        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=3600,
        )

        result = {
            "filename": attachment["filename"],
            "content-type": attachment["content-type"],
            "url": url,
        }

        if "content-id" in attachment:
            result["content-id"] = attachment["content-id"]

        results.append(result)

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_attachment_handler.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/attachment_handler.py tests/test_attachment_handler.py
git commit -m "feat: attachment handler uploads to S3 with signed URLs"
```

---

## Task 6: Webhook sender

**Files:**
- Create: `src/webhook_sender.py`
- Create: `tests/test_webhook_sender.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_webhook_sender.py`:

```python
import hashlib
import hmac
import json
import time
import pytest
import responses
from src.webhook_sender import send_webhook


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

        with pytest.raises(Exception, match="Webhook delivery failed"):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_webhook_sender.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Write implementation**

Create `src/webhook_sender.py`:

```python
import hashlib
import hmac
import json
import time
import requests


class WebhookDeliveryError(Exception):
    pass


def send_webhook(url: str, payload: dict, signing_secret: str) -> None:
    body = json.dumps(payload)
    timestamp = str(int(time.time()))

    signature = hmac.new(
        signing_secret.encode(),
        f"{timestamp}.{body}".encode(),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Signature": signature,
        "X-Timestamp": timestamp,
    }

    response = requests.post(url, data=body, headers=headers, timeout=30)

    if not response.ok:
        raise WebhookDeliveryError(
            f"Webhook delivery failed: {response.status_code} {response.text}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_webhook_sender.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/webhook_sender.py tests/test_webhook_sender.py
git commit -m "feat: webhook sender with HMAC-SHA256 signed POST"
```

---

## Task 7: Lambda handler

**Files:**
- Create: `src/handler.py`
- Create: `tests/test_handler.py`

This is the integration point. The handler:
1. Receives an SNS event (which contains the S3 bucket/key of the raw email)
2. Fetches the raw email from S3
3. Parses it with `email_parser`
4. Strips replies with `reply_stripper`
5. Uploads attachments with `attachment_handler`
6. Looks up webhook config with `config`
7. Sends the webhook with `webhook_sender`

- [ ] **Step 1: Write failing tests**

Create `tests/test_handler.py`:

```python
import json
import boto3
import pytest
import responses
from moto import mock_aws
from src.handler import lambda_handler


@pytest.fixture
def s3_setup(simple_html_email):
    """Set up S3 with a raw email and return bucket/key info."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="ses-incoming-emails")
        s3.create_bucket(Bucket="ses-email-attachments")
        s3.put_object(
            Bucket="ses-incoming-emails",
            Key="emails/abc123",
            Body=simple_html_email.encode(),
        )
        yield {
            "email_bucket": "ses-incoming-emails",
            "email_key": "emails/abc123",
            "attachment_bucket": "ses-email-attachments",
        }


def make_sns_event(s3_bucket, s3_key):
    """Create an SNS event that wraps an SES notification."""
    ses_notification = {
        "notificationType": "Received",
        "receipt": {
            "action": {
                "type": "S3",
                "bucketName": s3_bucket,
                "objectKey": s3_key,
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
    @responses.activate
    def test_end_to_end_processes_email_and_sends_webhook(self, simple_html_email, domain_config, monkeypatch):
        with mock_aws():
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

            event = make_sns_event("ses-incoming-emails", "emails/abc123")
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
            assert "body-html" in payload
            assert "body-plain" in payload
            assert "stripped-html" in payload
            assert "stripped-text" in payload

    @responses.activate
    def test_processes_email_with_attachment(self, email_with_attachment, domain_config, monkeypatch):
        with mock_aws():
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

            event = make_sns_event("ses-incoming-emails", "emails/att123")
            result = lambda_handler(event, None)

            assert result["statusCode"] == 200

            payload = json.loads(responses.calls[0].request.body)
            assert len(payload["attachments"]) == 1
            assert payload["attachments"][0]["filename"] == "photo.png"
            assert payload["attachments"][0]["content-type"] == "image/png"
            assert "url" in payload["attachments"][0]
            # Should not contain raw bytes
            assert "content" not in payload["attachments"][0]

    def test_returns_error_for_unknown_domain(self, simple_text_email, monkeypatch):
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket="ses-incoming-emails")
            s3.create_bucket(Bucket="ses-email-attachments")

            # Build email to unknown domain
            import email as email_lib
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

            event = make_sns_event("ses-incoming-emails", "emails/unknown")
            result = lambda_handler(event, None)

            assert result["statusCode"] == 400
            assert "not configured" in result["body"].lower() or "No config" in result["body"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_handler.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Write implementation**

Create `src/handler.py`:

```python
import json
import logging
import os
import boto3

from src.email_parser import parse_email
from src.reply_stripper import strip_reply
from src.attachment_handler import upload_attachments
from src.config import get_domain_config, DomainNotConfiguredError
from src.webhook_sender import send_webhook, WebhookDeliveryError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    try:
        # Extract S3 info from SNS > SES notification
        sns_message = json.loads(event["Records"][0]["Sns"]["Message"])
        action = sns_message["receipt"]["action"]
        email_bucket = action["bucketName"]
        email_key = action["objectKey"]

        # Fetch raw email from S3
        s3 = boto3.client("s3", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        response = s3.get_object(Bucket=email_bucket, Key=email_key)
        raw_email = response["Body"].read().decode("utf-8")

        # Parse email
        parsed = parse_email(raw_email)

        # Look up domain config
        domain = parsed["domain"]
        config = get_domain_config(domain)

        # Strip replies
        stripped = strip_reply(text=parsed["body-plain"], html=parsed["body-html"])

        # Upload attachments to S3
        attachment_bucket = os.environ["ATTACHMENT_BUCKET"]
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        uploaded_attachments = upload_attachments(parsed["attachments"], attachment_bucket, region)

        # Build webhook payload
        payload = {
            "sender": parsed["sender"],
            "recipient": parsed["recipient"],
            "subject": parsed["subject"],
            "message-id": parsed["message-id"],
            "in-reply-to": parsed["in-reply-to"],
            "references": parsed["references"],
            "body-html": parsed["body-html"],
            "body-plain": parsed["body-plain"],
            "stripped-html": stripped["stripped-html"],
            "stripped-text": stripped["stripped-text"],
            "attachments": uploaded_attachments,
        }

        # Send webhook
        send_webhook(config["webhook_url"], payload, config["signing_secret"])

        logger.info(f"Processed email from {parsed['sender']} to {parsed['recipient']}")
        return {"statusCode": 200, "body": "OK"}

    except DomainNotConfiguredError as e:
        logger.warning(f"Domain not configured: {e}")
        return {"statusCode": 400, "body": str(e)}

    except WebhookDeliveryError as e:
        logger.error(f"Webhook delivery failed: {e}")
        return {"statusCode": 502, "body": str(e)}

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {"statusCode": 500, "body": str(e)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/test_handler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full test suite**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/ -v`
Expected: All tests pass across all modules.

- [ ] **Step 6: Commit**

```bash
git add src/handler.py tests/test_handler.py
git commit -m "feat: Lambda handler orchestrates email parsing and webhook delivery"
```

---

## Task 8: SAM template

**Files:**
- Create: `template.yaml`

This task creates the AWS SAM template that defines all infrastructure. This is not TDD — it's declarative infrastructure verified with `sam validate`.

- [ ] **Step 1: Create `template.yaml`**

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: >
  Reusable inbound email gateway. Receives emails via SES, parses them,
  strips quoted replies, and POSTs JSON payloads to configured webhook URLs.

Parameters:
  DomainConfig:
    Type: String
    Description: >
      JSON mapping of domain to webhook config.
      Example: {"letterclub.org": {"webhook_url": "https://...", "signing_secret": "..."}}

Globals:
  Function:
    Timeout: 60
    MemorySize: 256
    Runtime: python3.13

Resources:
  IncomingEmailBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "${AWS::StackName}-incoming-emails"
      LifecycleConfiguration:
        Rules:
          - Id: DeleteOldEmails
            Status: Enabled
            ExpirationInDays: 30

  IncomingEmailBucketPolicy:
    Type: AWS::S3::BucketPolicy
    Properties:
      Bucket: !Ref IncomingEmailBucket
      PolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Sid: AllowSESPut
            Effect: Allow
            Principal:
              Service: ses.amazonaws.com
            Action: s3:PutObject
            Resource: !Sub "${IncomingEmailBucket.Arn}/*"
            Condition:
              StringEquals:
                "AWS:SourceAccount": !Ref "AWS::AccountId"

  AttachmentBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "${AWS::StackName}-attachments"
      LifecycleConfiguration:
        Rules:
          - Id: DeleteOldAttachments
            Status: Enabled
            ExpirationInDays: 7

  EmailNotificationTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: !Sub "${AWS::StackName}-email-notifications"

  EmailNotificationTopicPolicy:
    Type: AWS::SNS::TopicPolicy
    Properties:
      Topics:
        - !Ref EmailNotificationTopic
      PolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Sid: AllowSESPublish
            Effect: Allow
            Principal:
              Service: ses.amazonaws.com
            Action: sns:Publish
            Resource: !Ref EmailNotificationTopic
            Condition:
              StringEquals:
                "AWS:SourceAccount": !Ref "AWS::AccountId"

  InboundEmailFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: src/
      Handler: handler.lambda_handler
      Environment:
        Variables:
          DOMAIN_CONFIG: !Ref DomainConfig
          ATTACHMENT_BUCKET: !Ref AttachmentBucket
      Policies:
        - S3ReadPolicy:
            BucketName: !Ref IncomingEmailBucket
        - S3CrudPolicy:
            BucketName: !Ref AttachmentBucket
      Events:
        EmailNotification:
          Type: SNS
          Properties:
            Topic: !Ref EmailNotificationTopic

Outputs:
  IncomingEmailBucketName:
    Description: S3 bucket for raw incoming emails (configure in SES receipt rule)
    Value: !Ref IncomingEmailBucket

  EmailNotificationTopicArn:
    Description: SNS topic ARN (configure in SES receipt rule)
    Value: !Ref EmailNotificationTopic

  AttachmentBucketName:
    Description: S3 bucket for uploaded attachments
    Value: !Ref AttachmentBucket

  FunctionArn:
    Description: Lambda function ARN
    Value: !GetAtt InboundEmailFunction.Arn
```

- [ ] **Step 2: Validate the template**

Run: `cd /Users/srobbin/Git/ses-inbound-email && sam validate --lint` (requires SAM CLI installed)

If SAM CLI is not installed, validate by checking the YAML syntax:
Run: `python3 -c "import yaml; yaml.safe_load(open('template.yaml'))"`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add template.yaml
git commit -m "feat: SAM template for Lambda, S3, and SNS resources"
```

---

## Task 9: README and final cleanup

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create README.md**

```markdown
# SES Inbound Email Gateway

A reusable AWS Lambda that receives inbound emails via Amazon SES, parses them, strips quoted replies, and POSTs a clean JSON payload to a configured webhook URL.

## Architecture

```
Sender → SES → S3 (raw email) → SNS → Lambda → Webhook POST
```

## Setup

### Prerequisites

- AWS account with SES configured for your domain
- AWS SAM CLI
- Python 3.13+

### Configuration

The Lambda uses a `DOMAIN_CONFIG` environment variable (JSON) to map domains to webhook URLs:

```json
{
  "yourdomain.com": {
    "webhook_url": "https://yourdomain.com/webhooks/inbound",
    "signing_secret": "your-secret-key"
  }
}
```

### Deploy

```bash
sam build
sam deploy --guided
```

During guided deploy, you'll be prompted for the `DomainConfig` parameter.

### SES Receipt Rule

After deploying, create an SES receipt rule that:
1. Stores the email in the `IncomingEmailBucket` (from stack outputs)
2. Publishes a notification to the `EmailNotificationTopic` (from stack outputs)

## Webhook Payload

```json
{
  "sender": "user@example.com",
  "recipient": "reply+123@yourdomain.com",
  "subject": "Re: Your subject",
  "stripped-html": "<p>Just the reply</p>",
  "stripped-text": "Just the reply",
  "body-html": "<p>Full HTML</p>",
  "body-plain": "Full plain text",
  "message-id": "<abc@example.com>",
  "in-reply-to": "<def@yourdomain.com>",
  "references": "<def@yourdomain.com>",
  "attachments": [
    {
      "filename": "photo.jpg",
      "content-type": "image/jpeg",
      "url": "https://s3-signed-url..."
    }
  ]
}
```

## Webhook Verification

Each POST includes `X-Signature` and `X-Timestamp` headers. Verify with:

```python
import hmac, hashlib

expected = hmac.new(
    signing_secret.encode(),
    f"{timestamp}.{body}".encode(),
    hashlib.sha256
).hexdigest()

assert hmac.compare_digest(signature, expected)
```

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Adding a Domain

Add an entry to the `DOMAIN_CONFIG` JSON and update the Lambda environment variable:

```bash
aws lambda update-function-configuration \
  --function-name <function-name> \
  --environment "Variables={DOMAIN_CONFIG='...'}"
```

Then add an SES receipt rule for the new domain.
```

- [ ] **Step 2: Run the full test suite one final time**

Run: `cd /Users/srobbin/Git/ses-inbound-email && .venv/bin/pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup, deployment, and usage instructions"
```

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

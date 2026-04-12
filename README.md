# SES Inbound Email Gateway

A reusable AWS Lambda that receives inbound emails via Amazon SES, parses them, strips quoted replies, and POSTs a clean JSON payload to a configured webhook URL. Optionally forwards emails matching specific patterns to another address.

## Architecture

```
Sender → SES → S3 (raw email) → SNS → Lambda
                                         ├── Recipient matches forward pattern? → SES forward to destination
                                         └── Otherwise → Parse, strip reply → Webhook POST
```

## Setup

### Prerequisites

- AWS account with SES configured for your domain(s)
- SES out of sandbox mode (for forwarding to unverified addresses)
- AWS SAM CLI
- Python 3.13+

### Deploy

```bash
sam build
sam deploy --guided
```

During guided deploy, you'll be prompted for the `DomainConfig` parameter (see Configuration below).

### SES Receipt Rule

After deploying, create an SES receipt rule for your domain that:

1. **Stores** the email in the S3 bucket from the `IncomingEmailBucketName` stack output
2. **Notifies** the SNS topic from the `EmailNotificationTopicArn` stack output

### DNS

Point your domain's MX record to SES:

```
MX 10 inbound-smtp.us-east-1.amazonaws.com
```

Also verify the domain in SES (DKIM + SPF) for outbound sending (required for forwarding).

## Configuration

Configuration lives in two places: a JSON env var for non-secret per-domain settings, and SSM Parameter Store (SecureString) for each domain's signing secret.

### `DOMAIN_CONFIG` env var

The Lambda reads a `DOMAIN_CONFIG` environment variable — a JSON object mapping domains to their non-secret settings. Each domain must have a `webhook_url`. The `forwards` key is optional.

```json
{
  "yourdomain.com": {
    "webhook_url": "https://yourdomain.com/webhooks/inbound",
    "forwards": {
      "admin|support|billing": "you@example.com",
      "sales|partnerships": "sales@example.com"
    }
  },
  "another-app.com": {
    "webhook_url": "https://another-app.com/webhooks/inbound"
  }
}
```

### Signing secret in SSM Parameter Store

The HMAC signing secret for each domain lives in SSM Parameter Store as a SecureString, *not* in `DOMAIN_CONFIG`. The Lambda fetches it at runtime based on the recipient domain.

Store the secret under `/ses-inbound-email/<domain>/signing-secret`:

```bash
aws ssm put-parameter \
  --name "/ses-inbound-email/yourdomain.com/signing-secret" \
  --value "$(openssl rand -hex 32)" \
  --type SecureString \
  --region us-east-1
```

This keeps secret material out of git and out of Lambda environment variables. Rotation is a matter of running the above command with `--overwrite` and updating the consumer that verifies the signature.

### Forwarding

The `forwards` object maps regex patterns to destination email addresses. Patterns are matched against the **local part** (before the `@`) of the recipient address, case-insensitively. When a match is found, the raw email is forwarded via SES to the destination address and no webhook is sent.

If `forwards` is omitted or empty, all emails go to the webhook.

## Webhook Payload

Emails that don't match a forwarding pattern are parsed and POSTed as JSON to the configured `webhook_url`:

```json
{
  "sender": "user@example.com",
  "recipient": "reply+123@yourdomain.com",
  "subject": "Re: Your subject",
  "stripped-html": "<p>Just the reply</p>",
  "stripped-text": "Just the reply",
  "body-html": "<p>Full HTML with quoted parts</p>",
  "body-plain": "Full plain text with quoted parts",
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

Attachments are uploaded to S3 with 1-hour signed URLs. The `stripped-html` and `stripped-text` fields contain the reply only (quoted content removed via [quotequail](https://github.com/closeio/quotequail)). The `body-html` and `body-plain` fields contain the full email.

## Webhook Verification

Each POST includes `X-Signature` and `X-Timestamp` headers. Verify the signature to ensure the request came from your Lambda:

```python
import hmac, hashlib

expected = hmac.new(
    signing_secret.encode(),
    f"{timestamp}.{body}".encode(),
    hashlib.sha256
).hexdigest()

assert hmac.compare_digest(signature, expected)
```

Reject requests where the timestamp is more than 5 minutes old to prevent replay attacks.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Adding a Domain

A helper script automates SES setup for a new domain:

```bash
./scripts/add-domain.sh yourdomain.com
```

This will:

1. Create an SES email identity for the domain
2. Print the 3 DKIM CNAME records to add to your DNS
3. Wait for SES to verify the domain
4. Create an SES receipt rule to route inbound email to the Lambda

After the script completes, you still need to:

1. **Add DNS records** — the 3 DKIM CNAMEs (printed by the script)
2. **Add domain to Lambda config** — add an entry to `DOMAIN_CONFIG` in `samconfig.toml`:
   ```json
   {
     "yourdomain.com": {
       "webhook_url": "https://yourdomain.com/webhooks/inbound",
       "forwards": {
         "admin|support": "you@example.com"
       }
     }
   }
   ```
   The script already put the signing secret in SSM Parameter Store — no further action needed for that.
3. **Deploy** — `sam build && sam deploy`
4. **Point MX record to SES** — add to your DNS:
   ```
   MX 10 inbound-smtp.us-east-1.amazonaws.com
   ```

### Manual setup

If you prefer to set up manually or need to customize the process:

1. Create SES identity: `aws sesv2 create-email-identity --email-identity yourdomain.com --region us-east-1`
2. Add the 3 DKIM CNAME records to DNS (from the command output)
3. Wait for verification: `aws sesv2 get-email-identity --email-identity yourdomain.com --region us-east-1`
4. Create a receipt rule (see `scripts/add-domain.sh` for the exact command)
5. Add domain to `DOMAIN_CONFIG` in `samconfig.toml` and deploy
6. Point MX record to SES

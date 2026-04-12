#!/usr/bin/env bash
set -euo pipefail

# Add a new domain to the SES Inbound Email Gateway.
#
# This script:
# 1. Creates an SES email identity (triggers DKIM verification)
# 2. Prints the 3 CNAME records you need to add to DNS
# 3. Waits for SES to verify the domain
# 4. Adds an SES receipt rule for the domain
# 5. Generates a signing secret and stores it in SSM Parameter Store
#
# After running this script, you still need to:
# - Add the domain to DOMAIN_CONFIG in samconfig.toml and redeploy
# - Point the domain's MX record to inbound-smtp.<region>.amazonaws.com
#
# Usage: ./scripts/add-domain.sh <domain> [region]
# Example: ./scripts/add-domain.sh letterclub.org us-east-1

DOMAIN="${1:?Usage: $0 <domain> [region]}"
REGION="${2:-us-east-1}"
RULE_SET_NAME="ses-inbound-email"
S3_BUCKET="ses-inbound-email-incoming-emails"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:$(aws sts get-caller-identity --query Account --output text):ses-inbound-email-email-notifications"

echo "==> Setting up SES for domain: ${DOMAIN} in ${REGION}"
echo ""

# Step 1: Create email identity
echo "==> Creating SES email identity..."
TOKENS=$(aws sesv2 create-email-identity \
  --email-identity "${DOMAIN}" \
  --region "${REGION}" \
  --query 'DkimAttributes.Tokens' \
  --output text 2>&1) || {
    # Check if it already exists
    EXISTING=$(aws sesv2 get-email-identity \
      --email-identity "${DOMAIN}" \
      --region "${REGION}" \
      --query 'DkimAttributes.Tokens' \
      --output text 2>/dev/null) || true
    if [ -n "${EXISTING}" ]; then
      echo "    Domain already exists in SES."
      TOKENS="${EXISTING}"
    else
      echo "    Failed to create email identity."
      exit 1
    fi
  }

# Step 2: Print DKIM CNAME records
echo ""
echo "==> Add these CNAME records to your DNS:"
echo ""
for TOKEN in ${TOKENS}; do
  echo "    ${TOKEN}._domainkey.${DOMAIN} → ${TOKEN}.dkim.amazonses.com"
done
echo ""

# Step 3: Wait for verification
echo "==> Waiting for SES to verify domain (this may take a few minutes)..."
echo "    Press Ctrl+C to skip waiting — you can check status later with:"
echo "    aws sesv2 get-email-identity --email-identity ${DOMAIN} --region ${REGION}"
echo ""

for i in $(seq 1 30); do
  STATUS=$(aws sesv2 get-email-identity \
    --email-identity "${DOMAIN}" \
    --region "${REGION}" \
    --query 'DkimAttributes.Status' \
    --output text 2>/dev/null)

  if [ "${STATUS}" = "SUCCESS" ]; then
    echo "    Domain verified!"
    break
  fi

  if [ "${i}" -eq 30 ]; then
    echo "    Timed out waiting for verification. Add the DNS records and check back."
    echo "    Continuing with receipt rule setup..."
    break
  fi

  echo "    Status: ${STATUS} (attempt ${i}/30, retrying in 10s...)"
  sleep 10
done

# Step 4: Add receipt rule
echo ""
echo "==> Adding SES receipt rule for ${DOMAIN}..."

# Check if rule set exists
aws ses describe-receipt-rule-set \
  --rule-set-name "${RULE_SET_NAME}" \
  --region "${REGION}" > /dev/null 2>&1 || {
    echo "    Creating receipt rule set: ${RULE_SET_NAME}"
    aws ses create-receipt-rule-set \
      --rule-set-name "${RULE_SET_NAME}" \
      --region "${REGION}"
    aws ses set-active-receipt-rule-set \
      --rule-set-name "${RULE_SET_NAME}" \
      --region "${REGION}"
  }

RULE_NAME="${DOMAIN//\./-}-inbound"

aws ses create-receipt-rule \
  --rule-set-name "${RULE_SET_NAME}" \
  --region "${REGION}" \
  --rule "{
    \"Name\": \"${RULE_NAME}\",
    \"Enabled\": true,
    \"Recipients\": [\"${DOMAIN}\"],
    \"Actions\": [
      {
        \"S3Action\": {
          \"BucketName\": \"${S3_BUCKET}\",
          \"ObjectKeyPrefix\": \"emails/\"
        }
      },
      {
        \"SNSAction\": {
          \"TopicArn\": \"${SNS_TOPIC_ARN}\",
          \"Encoding\": \"UTF-8\"
        }
      }
    ],
    \"ScanEnabled\": true
  }" 2>&1 || echo "    Rule may already exist — check with: aws ses describe-active-receipt-rule-set --region ${REGION}"

# Step 5: Generate signing secret and store in SSM Parameter Store
echo ""
echo "==> Generating signing secret and storing in SSM Parameter Store..."

SSM_PARAM_NAME="/ses-inbound-email/${DOMAIN}/signing-secret"

if aws ssm get-parameter --name "${SSM_PARAM_NAME}" --region "${REGION}" > /dev/null 2>&1; then
  echo "    SSM parameter ${SSM_PARAM_NAME} already exists — skipping. Use --overwrite manually to rotate."
else
  SIGNING_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  aws ssm put-parameter \
    --name "${SSM_PARAM_NAME}" \
    --value "${SIGNING_SECRET}" \
    --type SecureString \
    --description "HMAC signing secret for ${DOMAIN} inbound webhook" \
    --region "${REGION}" > /dev/null
  echo "    Stored at ${SSM_PARAM_NAME}"
  echo "    You'll need to copy this value into the consumer that verifies the webhook signature:"
  echo "    ${SIGNING_SECRET}"
  echo "    (It will not be printed again. Retrieve later with:"
  echo "     aws ssm get-parameter --name ${SSM_PARAM_NAME} --with-decryption --region ${REGION})"
fi

echo ""
echo "==> Done! Next steps:"
echo ""
echo "    1. Add ${DOMAIN} to DOMAIN_CONFIG in samconfig.toml:"
echo ""
echo "       \"${DOMAIN}\": {"
echo "         \"webhook_url\": \"https://${DOMAIN}/webhooks/inbound\""
echo "       }"
echo ""
echo "    2. Deploy: sam build && sam deploy"
echo ""
echo "    3. Point MX record to SES:"
echo "       MX 10 inbound-smtp.${REGION}.amazonaws.com"
echo ""

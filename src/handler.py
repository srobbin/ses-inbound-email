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
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        s3 = boto3.client("s3", region_name=region)
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

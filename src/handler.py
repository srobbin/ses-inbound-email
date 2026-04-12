import json
import logging
import os
import boto3

from email_parser import parse_email
from reply_stripper import strip_reply
from attachment_handler import upload_attachments
from config import get_domain_config, DomainNotConfiguredError
from notification_handler import handle_bounce, handle_complaint
from webhook_sender import send_webhook, WebhookDeliveryError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    try:
        sns_message = json.loads(event["Records"][0]["Sns"]["Message"])
        notification_type = sns_message.get("notificationType")

        # Route bounce/complaint notifications to dedicated handlers
        if notification_type == "Bounce":
            return handle_bounce(sns_message)
        if notification_type == "Complaint":
            return handle_complaint(sns_message)

        logger.info(f"SES notification action: {json.dumps(sns_message['receipt']['action'])}")

        # The receipt.action reflects whichever action triggered this notification.
        # When the SNS action triggers the Lambda, it contains the SNS action type
        # (not the S3 action). Construct the S3 key from mail.messageId instead.
        mail_message_id = sns_message["mail"]["messageId"]
        email_bucket = os.environ.get("INCOMING_EMAIL_BUCKET")
        email_key = f"emails/{mail_message_id}"

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

        # Check if this email should be forwarded
        forwards = config.get("forwards")
        if forwards:
            from forwarder import check_forward, forward_email
            destination = check_forward(parsed["recipient"], forwards)
            if destination:
                forward_email(raw_email, parsed["recipient"], destination, region)
                logger.info(f"Forwarded {parsed['recipient']} to {destination}, skipping webhook")
                return {"statusCode": 200, "body": "Forwarded"}

        # Strip replies
        stripped = strip_reply(text=parsed["body-plain"], html=parsed["body-html"])

        # Upload attachments to S3
        attachment_bucket = os.environ["ATTACHMENT_BUCKET"]
        uploaded_attachments = upload_attachments(parsed["attachments"], attachment_bucket, region)

        # Build webhook payload
        payload = {
            "event": "inbound",
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

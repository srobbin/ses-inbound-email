import json
import logging
import os
import boto3

from email_parser import parse_email
from reply_stripper import strip_reply
from attachment_handler import upload_attachments
from config import get_domain_config, DomainNotConfiguredError
from notification_handler import handle_bounce, handle_complaint
from webhook_sender import send_webhook

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    try:
        # SQS wraps the SNS message: parse SQS body, then SNS Message
        sqs_body = json.loads(event["Records"][0]["body"])
        sns_message = json.loads(sqs_body["Message"])

        # Route bounce/complaint notifications to dedicated handlers.
        # SES receipt notifications use "notificationType"; Configuration Set
        # event destinations use "eventType".  Both are uppercase values.
        notification_type = sns_message.get("notificationType") or sns_message.get("eventType")
        if notification_type == "Bounce":
            return handle_bounce(sns_message)
        if notification_type == "Complaint":
            return handle_complaint(sns_message)

        # Inbound emails arrive as S3 event notifications (triggered when
        # SES writes the raw email to the incoming-email bucket).
        s3_record = sns_message["Records"][0]["s3"]
        email_bucket = s3_record["bucket"]["name"]
        email_key = s3_record["object"]["key"]

        logger.info(f"Processing email: s3://{email_bucket}/{email_key}")

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

        # Send webhook — let WebhookDeliveryError propagate so SQS retries
        send_webhook(config["webhook_url"], payload, config["signing_secret"])

        logger.info(f"Processed email from {parsed['sender']} to {parsed['recipient']}")
        return {"statusCode": 200, "body": "OK"}

    except DomainNotConfiguredError as e:
        logger.warning(f"Domain not configured (message discarded): {e}")
        return {"statusCode": 200, "body": str(e)}

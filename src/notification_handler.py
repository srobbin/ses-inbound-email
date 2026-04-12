import logging

from config import get_domain_config
from webhook_sender import send_webhook

logger = logging.getLogger()


def handle_bounce(sns_message: dict) -> dict:
    """Process an SES bounce notification and send a webhook event."""
    bounce = sns_message["bounce"]
    mail = sns_message["mail"]

    source_domain = mail["source"].split("@", 1)[1]
    config = get_domain_config(source_domain)

    for recipient in bounce["bouncedRecipients"]:
        payload = {
            "event": "bounced",
            "recipient": recipient["emailAddress"],
            "sender": mail["source"],
            "bounce_type": bounce["bounceType"],
            "bounce_subtype": bounce["bounceSubType"],
            "diagnostic": recipient.get("diagnosticCode", ""),
            "message-id": mail.get("messageId", ""),
            "timestamp": bounce["timestamp"],
        }

        send_webhook(config["webhook_url"], payload, config["signing_secret"])
        logger.info(f"Sent bounce webhook for {recipient['emailAddress']}")

    return {"statusCode": 200, "body": "Bounce processed"}


def handle_complaint(sns_message: dict) -> dict:
    """Process an SES complaint notification and send a webhook event."""
    complaint = sns_message["complaint"]
    mail = sns_message["mail"]

    source_domain = mail["source"].split("@", 1)[1]
    config = get_domain_config(source_domain)

    for recipient in complaint["complainedRecipients"]:
        payload = {
            "event": "complained",
            "recipient": recipient["emailAddress"],
            "sender": mail["source"],
            "complaint_type": complaint.get("complaintFeedbackType", ""),
            "message-id": mail.get("messageId", ""),
            "timestamp": complaint["timestamp"],
        }

        send_webhook(config["webhook_url"], payload, config["signing_secret"])
        logger.info(f"Sent complaint webhook for {recipient['emailAddress']}")

    return {"statusCode": 200, "body": "Complaint processed"}

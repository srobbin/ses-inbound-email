import re
import boto3
import logging

logger = logging.getLogger()


def check_forward(recipient: str, forwards: dict) -> str | None:
    """Check if recipient matches a forwarding pattern. Returns destination email or None."""
    if not forwards:
        return None

    local_part = recipient.split("@")[0] if "@" in recipient else recipient

    for pattern, destination in forwards.items():
        if re.match(f"^({pattern})$", local_part, re.IGNORECASE):
            return destination

    return None


def forward_email(raw_email: str, recipient: str, destination: str, region: str) -> None:
    """Forward a raw email via SES to the destination address."""
    import email as email_lib
    from email.utils import parseaddr

    msg = email_lib.message_from_string(raw_email)
    original_from = parseaddr(msg["From"])[1]

    # Keep the original To header (e.g. support@letterclub.org) so the
    # recipient can see who the email was originally addressed to.
    # Only the envelope destination is changed to route delivery.
    ses = boto3.client("ses", region_name=region)
    ses.send_raw_email(
        Source=original_from,
        Destinations=[destination],
        RawMessage={"Data": msg.as_string()},
    )

    logger.info(f"Forwarded email from {original_from} to {destination} (original recipient: {recipient})")

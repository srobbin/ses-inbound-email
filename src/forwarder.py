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
    from email.utils import formataddr, parseaddr

    msg = email_lib.message_from_string(raw_email)
    original_name, original_from = parseaddr(msg["From"])

    # SES re-signs outgoing mail and rejects messages that already carry
    # authentication headers, so strip anything the inbound hop added.
    for header in (
        "DKIM-Signature",
        "Return-Path",
        "Received-SPF",
        "Authentication-Results",
        "X-SES-DKIM-SIGNATURE",
    ):
        del msg[header]

    # SES requires Source to be a verified identity on a domain we own, so
    # send as info@<recipient-domain> and rewrite From accordingly. The real
    # sender goes to Reply-To so replies still reach them, and DMARC on the
    # recipient side sees a From aligned with our signing domain.
    recipient_domain = recipient.split("@", 1)[1]
    source = f"info@{recipient_domain}"
    display_name = f"{original_name} via {recipient_domain}" if original_name else f"{original_from} via {recipient_domain}"

    del msg["From"]
    msg["From"] = formataddr((display_name, source))
    del msg["Reply-To"]
    msg["Reply-To"] = formataddr((original_name, original_from)) if original_name else original_from

    ses = boto3.client("ses", region_name=region)
    ses.send_raw_email(
        Source=source,
        Destinations=[destination],
        RawMessage={"Data": msg.as_string()},
    )

    logger.info(f"Forwarded email from {original_from} to {destination} (original recipient: {recipient})")

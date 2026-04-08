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
                body_plain = part.get_content().strip()
            elif content_type == "text/html" and body_html is None:
                body_html = part.get_content().strip()
    else:
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            body_plain = msg.get_content().strip()
        elif content_type == "text/html":
            body_html = msg.get_content().strip()

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

import hashlib
import hmac
import json
import time
import requests


class WebhookDeliveryError(Exception):
    pass


def send_webhook(url: str, payload: dict, signing_secret: str) -> None:
    body = json.dumps(payload)
    timestamp = str(int(time.time()))

    signature = hmac.new(
        signing_secret.encode(),
        f"{timestamp}.{body}".encode(),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Signature": signature,
        "X-Timestamp": timestamp,
    }

    try:
        response = requests.post(url, data=body, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise WebhookDeliveryError(f"Webhook delivery failed: {e}") from e

    if not response.ok:
        raise WebhookDeliveryError(
            f"Webhook delivery failed: {response.status_code} {response.text}"
        )

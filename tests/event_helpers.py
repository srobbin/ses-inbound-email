import json


def make_s3_event(bucket, key):
    """Build an SQS event wrapping an SNS-wrapped S3 event notification."""
    s3_event = {
        "Records": [
            {
                "eventSource": "aws:s3",
                "eventName": "ObjectCreated:Put",
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                },
            }
        ]
    }
    sns_envelope = {
        "Type": "Notification",
        "Message": json.dumps(s3_event),
    }
    return {
        "Records": [
            {
                "body": json.dumps(sns_envelope),
            }
        ]
    }


def make_ses_notification_event(notification):
    """Build an SQS event wrapping an SNS-wrapped SES notification (bounce/complaint)."""
    sns_envelope = {
        "Type": "Notification",
        "Message": json.dumps(notification),
    }
    return {
        "Records": [{"body": json.dumps(sns_envelope)}]
    }

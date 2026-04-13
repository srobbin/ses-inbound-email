import uuid
import boto3
from botocore.config import Config


_s3_client = None


def _get_s3_client(region: str):
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=region, config=Config(signature_version="s3v4"))
    return _s3_client


def upload_attachments(attachments: list[dict], bucket: str, region: str) -> list[dict]:
    if not attachments:
        return []

    s3 = _get_s3_client(region)
    results = []

    for attachment in attachments:
        key = f"attachments/{uuid.uuid4()}/{attachment['filename']}"

        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=attachment["content"],
            ContentType=attachment["content-type"],
        )

        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=86400,
        )

        result = {
            "filename": attachment["filename"],
            "content-type": attachment["content-type"],
            "url": url,
        }

        if "content-id" in attachment:
            result["content-id"] = attachment["content-id"]

        results.append(result)

    return results

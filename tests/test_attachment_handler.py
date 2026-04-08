import boto3
import pytest
from moto import mock_aws
from attachment_handler import upload_attachments


class TestUploadAttachments:
    @mock_aws
    def test_uploads_attachment_to_s3_and_returns_signed_url(self):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-attachments")

        attachments = [
            {
                "filename": "photo.png",
                "content-type": "image/png",
                "content": b"\x89PNG fake image data",
            }
        ]

        result = upload_attachments(attachments, "test-attachments", "us-east-1")

        assert len(result) == 1
        assert result[0]["filename"] == "photo.png"
        assert result[0]["content-type"] == "image/png"
        assert "url" in result[0]
        assert "test-attachments" in result[0]["url"]
        assert "content" not in result[0]

    @mock_aws
    def test_uploads_multiple_attachments(self):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-attachments")

        attachments = [
            {"filename": "photo1.png", "content-type": "image/png", "content": b"image1"},
            {"filename": "photo2.jpg", "content-type": "image/jpeg", "content": b"image2"},
        ]

        result = upload_attachments(attachments, "test-attachments", "us-east-1")

        assert len(result) == 2
        assert result[0]["filename"] == "photo1.png"
        assert result[1]["filename"] == "photo2.jpg"

    @mock_aws
    def test_returns_empty_list_for_no_attachments(self):
        result = upload_attachments([], "test-attachments", "us-east-1")
        assert result == []

    @mock_aws
    def test_preserves_content_id_for_inline_images(self):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-attachments")

        attachments = [
            {
                "filename": "inline.png",
                "content-type": "image/png",
                "content": b"inline image",
                "content-id": "<img001>",
            }
        ]

        result = upload_attachments(attachments, "test-attachments", "us-east-1")

        assert result[0]["content-id"] == "<img001>"

    @mock_aws
    def test_s3_key_includes_filename(self):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-attachments")

        attachments = [
            {"filename": "photo.png", "content-type": "image/png", "content": b"data"}
        ]

        result = upload_attachments(attachments, "test-attachments", "us-east-1")

        assert "photo.png" in result[0]["url"]

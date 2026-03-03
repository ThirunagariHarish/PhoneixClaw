"""
Pull skills from MinIO to local directory. M1.7.
"""
import os
from pathlib import Path

from src.config import settings

SKILLS_DIR = Path(settings.AGENTS_ROOT).parent / "skills"
SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def sync_skills() -> dict:
    try:
        import boto3
        from botocore.config import Config
        endpoint = settings.MINIO_ENDPOINT
        if "://" not in endpoint:
            endpoint = ("https://" if settings.MINIO_USE_SSL else "http://") + endpoint
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.MINIO_ACCESS_KEY or os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
            aws_secret_access_key=settings.MINIO_SECRET_KEY or os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = settings.MINIO_BUCKET_SKILLS
        paginator = client.get_paginator("list_objects_v2")
        count = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=""):
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                local = SKILLS_DIR / key
                local.parent.mkdir(parents=True, exist_ok=True)
                client.download_file(bucket, key, str(local))
                count += 1
        return {"synced": count, "status": "ok"}
    except Exception as e:
        return {"synced": 0, "status": "error", "message": str(e)}

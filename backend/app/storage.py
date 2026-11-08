"""S3 / MinIO obyekt ombori."""
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.client import Config

from app.config import get_settings


@lru_cache
def _client(public: bool = False):
    s = get_settings()
    endpoint = (s.s3_public_endpoint_url or s.s3_endpoint_url) if public else s.s3_endpoint_url
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket() -> None:
    s = get_settings()
    client = _client()
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    if s.s3_bucket not in existing:
        client.create_bucket(Bucket=s.s3_bucket)


def upload_file(path: str | Path, key: str, content_type: str | None = None) -> str:
    extra = {"ContentType": content_type} if content_type else None
    _client().upload_file(str(path), get_settings().s3_bucket, key, ExtraArgs=extra)
    return key


def upload_fileobj(fileobj, key: str, content_type: str | None = None) -> str:
    extra = {"ContentType": content_type} if content_type else None
    _client().upload_fileobj(fileobj, get_settings().s3_bucket, key, ExtraArgs=extra)
    return key


def upload_bytes(data: bytes, key: str, content_type: str | None = None) -> str:
    kwargs = {"ContentType": content_type} if content_type else {}
    _client().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=data, **kwargs)
    return key


def download_file(key: str, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(get_settings().s3_bucket, key, str(path))
    return path


def presigned_url(key: str | None, download_name: str | None = None) -> str | None:
    if not key:
        return None
    s = get_settings()
    params = {"Bucket": s.s3_bucket, "Key": key}
    if download_name:
        params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
    return _client(public=True).generate_presigned_url(
        "get_object", Params=params, ExpiresIn=s.presign_ttl_seconds
    )

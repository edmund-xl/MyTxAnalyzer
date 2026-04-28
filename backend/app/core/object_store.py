from __future__ import annotations

import hashlib
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings


class ObjectStore:
    def __init__(
        self,
        mode: str | None = None,
        bucket: str | None = None,
        local_root: str | Path | None = None,
    ) -> None:
        self.mode = (mode or settings.object_store_mode).lower()
        self.bucket = bucket or settings.minio_bucket
        self.local_root = Path(local_root or settings.resolve_path(settings.local_artifact_root))
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.minio_endpoint,
                aws_access_key_id=settings.minio_access_key,
                aws_secret_access_key=settings.minio_secret_key,
                config=Config(signature_version="s3v4"),
                region_name="us-east-1",
            )
        return self._client

    def ensure_bucket(self) -> None:
        if self.mode == "local":
            self.local_root.mkdir(parents=True, exist_ok=True)
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def sha256_file(self, path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def sha256_bytes(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def put_file(self, local_path: str | Path, object_path: str) -> str:
        local_path = Path(local_path)
        self.ensure_bucket()
        if self.mode == "local":
            target = self.local_root / object_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(local_path.read_bytes())
            return f"file://{target}"
        self.client.upload_file(str(local_path), self.bucket, object_path)
        return f"s3://{self.bucket}/{object_path}"

    def put_bytes(self, content: bytes, object_path: str, content_type: str = "application/octet-stream") -> str:
        self.ensure_bucket()
        if self.mode == "local":
            target = self.local_root / object_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            return f"file://{target}"
        self.client.put_object(Bucket=self.bucket, Key=object_path, Body=content, ContentType=content_type)
        return f"s3://{self.bucket}/{object_path}"

    def get_bytes(self, object_path: str) -> bytes:
        object_path = self._strip_uri(object_path)
        if self.mode == "local":
            return (self.local_root / object_path).read_bytes()
        obj = self.client.get_object(Bucket=self.bucket, Key=object_path)
        return obj["Body"].read()

    def get_file(self, object_path: str, local_path: str | Path) -> Path:
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(self.get_bytes(object_path))
        return local_path

    def copy_object(self, source_path: str, target_path: str, content_type: str = "application/octet-stream") -> str:
        return self.put_bytes(self.get_bytes(source_path), target_path, content_type)

    def list_prefix(self, prefix: str) -> list[str]:
        prefix = self._strip_uri(prefix)
        if self.mode == "local":
            root = self.local_root / prefix
            if not root.exists():
                return []
            return sorted(str(path.relative_to(self.local_root)) for path in root.rglob("*") if path.is_file())
        paginator = self.client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)

    def _strip_uri(self, object_path: str) -> str:
        if object_path.startswith(f"s3://{self.bucket}/"):
            return object_path.removeprefix(f"s3://{self.bucket}/")
        if object_path.startswith("file://"):
            path = Path(object_path.removeprefix("file://"))
            try:
                return path.relative_to(self.local_root).as_posix()
            except ValueError:
                return path.as_posix()
        return object_path.lstrip("/")


def get_object_store() -> ObjectStore:
    return ObjectStore()

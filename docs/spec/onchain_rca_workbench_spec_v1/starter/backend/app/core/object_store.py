from __future__ import annotations

import hashlib
from pathlib import Path

class ObjectStore:
    """Placeholder object-store abstraction.

    Codex should implement S3/MinIO support using boto3.
    """

    def sha256_file(self, path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def put_file(self, local_path: str | Path, object_path: str) -> str:
        # TODO: upload to MinIO/S3 and return object path
        return object_path

    def list_prefix(self, prefix: str) -> list[str]:
        # TODO: list objects under prefix
        return []

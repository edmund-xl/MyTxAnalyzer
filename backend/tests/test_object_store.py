from __future__ import annotations

from app.core.object_store import ObjectStore


def test_local_object_store_put_get_list(tmp_path):
    store = ObjectStore(mode="local", local_root=tmp_path)
    uri = store.put_bytes(b"artifact", "cases/c1/a.txt", "text/plain")
    assert uri.startswith("file://")
    assert store.get_bytes("cases/c1/a.txt") == b"artifact"
    assert store.list_prefix("cases/c1") == ["cases/c1/a.txt"]
    assert store.sha256_bytes(b"artifact")

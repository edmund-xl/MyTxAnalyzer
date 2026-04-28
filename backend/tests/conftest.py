from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_rca_workbench.db")
os.environ.setdefault("OBJECT_STORE_MODE", "local")
os.environ.setdefault("LOCAL_ARTIFACT_ROOT", "./.test_artifacts")
os.environ.setdefault("WORKFLOW_MODE", "inline")
os.environ.setdefault("MEGAETH_RPC_URL", "http://localhost:8545")
os.environ.setdefault("MEGAETH_EXPLORER_API_KEY", "test")

from app.core.database import Base, engine, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import db as models  # noqa: E402,F401
from app.services.network_service import NetworkService  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    artifact_root = Path("./.test_artifacts")
    if artifact_root.exists():
        shutil.rmtree(artifact_root)
    session = SessionLocal()
    try:
        NetworkService(session).seed_from_config()
    finally:
        session.close()
    yield


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

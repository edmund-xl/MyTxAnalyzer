from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    from app.models import db  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_runtime_columns()
    ensure_runtime_indexes()


def ensure_runtime_columns() -> None:
    from sqlalchemy import inspect

    inspector = inspect(engine)
    if "networks" not in inspector.get_table_names():
        return
    network_columns = {column["name"] for column in inspector.get_columns("networks")}
    statements = []
    if "network_type" not in network_columns:
        statements.append("ALTER TABLE networks ADD COLUMN network_type VARCHAR(32) NOT NULL DEFAULT 'evm'")
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_runtime_indexes() -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_cases_status_updated ON cases (status, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_cases_network_updated ON cases (network_key, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_cases_updated ON cases (updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_case_block ON transactions (case_id, block_number)",
        "CREATE INDEX IF NOT EXISTS idx_evidence_case_created ON evidence (case_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_reports_case_version ON reports (case_id, version)",
        "CREATE INDEX IF NOT EXISTS idx_job_runs_case_created ON job_runs (case_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_case_created ON workflow_runs (case_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs (status)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

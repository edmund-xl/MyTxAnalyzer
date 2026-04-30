from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import WorkflowRun, utcnow


class WorkflowRunService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def start(self, case_id: str, workflow_id: str, mode: str, metadata: dict | None = None) -> WorkflowRun:
        existing = self.db.scalar(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id))
        if existing:
            existing.status = "running"
            existing.mode = mode
            existing.metadata_json = {**(existing.metadata_json or {}), **(metadata or {})}
            existing.started_at = existing.started_at or utcnow()
            existing.ended_at = None
            existing.error = None
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        row = WorkflowRun(
            case_id=case_id,
            workflow_id=workflow_id,
            mode=mode,
            status="running",
            started_at=utcnow(),
            metadata_json=metadata or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def finish(self, workflow_run_id: str, status: str, metadata: dict | None = None, error: str | None = None) -> WorkflowRun | None:
        row = self.db.get(WorkflowRun, workflow_run_id)
        if row is None:
            return None
        row.status = status
        row.metadata_json = {**(row.metadata_json or {}), **(metadata or {})}
        row.error = error
        row.ended_at = utcnow()
        row.updated_at = utcnow()
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def cancel(self, workflow_run_id: str) -> WorkflowRun | None:
        return self.finish(workflow_run_id, "cancelled")

    def list_for_case(self, case_id: str, limit: int = 50, offset: int = 0) -> list[WorkflowRun]:
        query = (
            select(WorkflowRun)
            .where(WorkflowRun.case_id == case_id)
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(query).all())

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.db import JobRun, utcnow


class JobService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def start(self, case_id: str, job_name: str, input_payload: dict | None = None) -> JobRun:
        job = JobRun(
            case_id=case_id,
            job_name=job_name,
            status="running",
            input=input_payload or {},
            started_at=utcnow(),
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def finish(self, job: JobRun, status: str, output: dict | None = None, error: str | None = None) -> JobRun:
        job.status = status
        job.output = output or {}
        job.error = error
        job.ended_at = utcnow()
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def list_for_case(self, case_id: str, limit: int = 100, offset: int = 0) -> list[JobRun]:
        query = (
            select(JobRun)
            .where(JobRun.case_id == case_id)
            .order_by(JobRun.created_at.desc(), JobRun.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(query).all())

    @contextmanager
    def run(self, case_id: str, job_name: str, input_payload: dict | None = None) -> Iterator[JobRun]:
        job = self.start(case_id, job_name, input_payload)
        try:
            yield job
        except Exception as exc:
            self.finish(job, "failed", error=str(exc))
            raise

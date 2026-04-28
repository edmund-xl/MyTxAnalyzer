from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.object_store import ObjectStore
from app.models.schemas import WorkerResult
from app.services.job_service import JobService
from app.services.report_service import ReportService


class ReportWorker:
    name = "report_worker"

    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def run(self, case_id: str, language: str | None = None, report_format: str = "markdown") -> WorkerResult:
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {"language": language, "format": report_format})
        try:
            report = ReportService(self.db, self.object_store).create_report(case_id, language=language, report_format=report_format, created_by=self.name)
            output = {"report_id": report.id, "version": report.version, "object_path": report.object_path}
            job_service.finish(job, "success", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="success", summary=output, artifacts=[report.object_path] if report.object_path else [])
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, error=str(exc))

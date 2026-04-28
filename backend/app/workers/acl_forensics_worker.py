from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import FindingCreate, WorkerResult
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService
from app.services.job_service import JobService


class ACLForensicsWorker:
    name = "acl_forensics_worker"

    def __init__(self, db: Session) -> None:
        self.db = db

    def run(self, case_id: str) -> WorkerResult:
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {})
        try:
            evidence = EvidenceService(self.db).list_for_case(case_id)
            role_events = [
                item
                for item in evidence
                if item.source_type == "receipt_log" and str(item.decoded.get("event", "")).lower() in {"rolegranted", "rolerevoked"}
            ]
            finding_ids: list[str] = []
            if role_events:
                claim = f"Detected {len(role_events)} AccessControl role grant/revoke event(s) relevant to the case."
                finding = FindingService(self.db).create_finding(
                    case_id,
                    FindingCreate(
                        title="AccessControl role changes detected",
                        finding_type="access_control",
                        severity="high",
                        confidence="high",
                        claim=claim,
                        rationale="RoleGranted/RoleRevoked logs are deterministic permission evidence.",
                        falsification="Historical role checks and source validation should be added for final publication.",
                        evidence_ids=[item.id for item in role_events],
                        created_by=self.name,
                    ),
                )
                finding_ids.append(finding.id)
            output = {"role_event_count": len(role_events), "finding_ids": finding_ids}
            job_service.finish(job, "success" if role_events else "partial", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="success" if role_events else "partial", summary=output, evidence_ids=[item.id for item in role_events])
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, error=str(exc))

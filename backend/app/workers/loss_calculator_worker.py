from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import WorkerResult
from app.services.evidence_service import EvidenceService
from app.services.job_service import JobService


class LossCalculatorWorker:
    name = "loss_calculator_worker"

    def __init__(self, db: Session) -> None:
        self.db = db

    def run(self, case_id: str) -> WorkerResult:
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {})
        try:
            fund_evidence = [
                item
                for item in EvidenceService(self.db).list_for_case(case_id)
                if item.source_type in {"balance_diff", "receipt_log"}
                and item.claim_key in {"native_value_transfer", "transfer", "sui_reward_redemption_flow"}
            ]
            evidence = EvidenceService(self.db).create_evidence(
                case_id=case_id,
                source_type="artifact_summary",
                producer=self.name,
                claim_key="loss_calculation_status",
                raw_path=None,
                decoded={
                    "fund_flow_evidence_count": len(fund_evidence),
                    "usd_loss": None,
                    "reason": "No price source configured; token-denominated evidence retained.",
                },
                confidence="partial",
            )
            output = {"fund_flow_evidence_count": len(fund_evidence), "usd_loss": None}
            job_service.finish(job, "partial", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="partial", summary=output, evidence_ids=[evidence.id])
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, error=str(exc))

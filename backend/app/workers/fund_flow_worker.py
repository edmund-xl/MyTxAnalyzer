from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import FindingCreate, WorkerResult
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService
from app.services.job_service import JobService


class FundFlowWorker:
    name = "fund_flow_worker"

    def __init__(self, db: Session) -> None:
        self.db = db

    def run(self, case_id: str) -> WorkerResult:
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {})
        evidence_ids: list[str] = []
        finding_ids: list[str] = []
        try:
            txs = CaseService(self.db).list_transactions(case_id)
            for tx in txs:
                if tx.value_wei and int(tx.value_wei) > 0:
                    evidence = EvidenceService(self.db).create_evidence(
                        case_id=case_id,
                        tx_id=tx.id,
                        source_type="balance_diff",
                        producer=self.name,
                        claim_key="native_value_transfer",
                        raw_path=None,
                        decoded={"tx_hash": tx.tx_hash, "from": tx.from_address, "to": tx.to_address, "value_wei": str(tx.value_wei)},
                        confidence="high",
                    )
                    evidence_ids.append(evidence.id)
            transfer_logs = [
                item
                for item in EvidenceService(self.db).list_for_case(case_id)
                if (item.source_type == "receipt_log" and str(item.decoded.get("event", "")).lower() == "transfer")
                or (item.source_type == "balance_diff" and item.claim_key == "sui_reward_redemption_flow")
            ]
            evidence_ids.extend(item.id for item in transfer_logs)
            if evidence_ids:
                finding = FindingService(self.db).create_finding(
                    case_id,
                    FindingCreate(
                        title="Asset movement evidence detected",
                        finding_type="fund_flow",
                        severity="high",
                        confidence="high",
                        claim=f"Detected {len(evidence_ids)} native/token transfer evidence item(s).",
                        rationale="Transfer logs and native value movement are deterministic fund-flow evidence.",
                        falsification="USD valuation and cross-chain destination confirmation remain separate checks.",
                        evidence_ids=evidence_ids,
                        created_by=self.name,
                    ),
                )
                finding_ids.append(finding.id)
            output = {"fund_flow_evidence_count": len(evidence_ids), "finding_ids": finding_ids}
            job_service.finish(job, "success" if evidence_ids else "partial", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="success" if evidence_ids else "partial", summary=output, evidence_ids=evidence_ids)
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, evidence_ids=evidence_ids, error=str(exc))

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import FindingCreate, WorkerResult
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService
from app.services.job_service import JobService


class SafeForensicsWorker:
    name = "safe_forensics_worker"

    def __init__(self, db: Session) -> None:
        self.db = db

    def run(self, case_id: str) -> WorkerResult:
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {})
        evidence_ids: list[str] = []
        finding_ids: list[str] = []
        try:
            txs = CaseService(self.db).list_transactions(case_id)
            safe_txs = [tx for tx in txs if tx.method_selector in {"0x6a761202", "0x8d80ff0a"} or tx.method_name in {"execTransaction", "multiSend"}]
            for tx in safe_txs:
                evidence = EvidenceService(self.db).create_evidence(
                    case_id=case_id,
                    tx_id=tx.id,
                    source_type="trace_call",
                    producer=self.name,
                    claim_key="safe_execution_detected",
                    raw_path=None,
                    decoded={"tx_hash": tx.tx_hash, "safe": tx.to_address, "method": tx.method_name or tx.method_selector, "signature_recovery": "pending"},
                    confidence="medium",
                )
                evidence_ids.append(evidence.id)
            if evidence_ids:
                finding = FindingService(self.db).create_finding(
                    case_id,
                    FindingCreate(
                        title="Gnosis Safe execution path detected",
                        finding_type="multisig",
                        severity="medium",
                        confidence="medium",
                        claim="At least one transaction uses a Safe execution selector; signer recovery remains required for high confidence.",
                        rationale="Safe selector evidence was decoded from transaction input.",
                        falsification="High-confidence signer attribution requires ECDSA/approvedHash/ERC1271 evidence.",
                        evidence_ids=evidence_ids,
                        created_by=self.name,
                    ),
                )
                finding_ids.append(finding.id)
            output = {"safe_transaction_count": len(safe_txs), "finding_ids": finding_ids}
            job_service.finish(job, "success" if safe_txs else "partial", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="success" if safe_txs else "partial", summary=output, evidence_ids=evidence_ids)
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, evidence_ids=evidence_ids, error=str(exc))

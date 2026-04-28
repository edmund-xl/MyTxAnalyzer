from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.object_store import ObjectStore
from app.models.schemas import WorkerResult
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.job_service import JobService


KNOWN_SELECTORS = {
    "0x6a761202": "execTransaction",
    "0x8d80ff0a": "multiSend",
    "0x2f2ff15d": "grantRole",
    "0xd547741f": "revokeRole",
    "0x095ea7b3": "approve",
    "0xa9059cbb": "transfer",
    "0x23b872dd": "transferFrom",
}


class DecodeWorker:
    name = "decode_worker"

    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def run(self, case_id: str) -> WorkerResult:
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {})
        evidence_ids: list[str] = []
        try:
            txs = CaseService(self.db).list_transactions(case_id)
            for tx in txs:
                selector = tx.method_selector or (tx.metadata_json or {}).get("input", "")[:10]
                if selector and selector != "0x":
                    tx.method_selector = selector
                    tx.method_name = KNOWN_SELECTORS.get(selector, "unknown")
                    self.db.add(tx)
                    evidence = EvidenceService(self.db).create_evidence(
                        case_id=case_id,
                        tx_id=tx.id,
                        source_type="trace_call",
                        producer=self.name,
                        claim_key="top_level_call_decoded",
                        raw_path=None,
                        decoded={"tx_hash": tx.tx_hash, "method_selector": selector, "method_name": tx.method_name},
                        confidence="medium" if tx.method_name == "unknown" else "high",
                    )
                    evidence_ids.append(evidence.id)
                for log in (tx.metadata_json or {}).get("decoded_logs", []):
                    evidence = EvidenceService(self.db).create_evidence(
                        case_id=case_id,
                        tx_id=tx.id,
                        source_type="receipt_log",
                        producer=self.name,
                        claim_key=log.get("claim_key") or (log.get("event") or "receipt_log").lower(),
                        raw_path=None,
                        decoded=log,
                        confidence="high",
                    )
                    evidence_ids.append(evidence.id)
            self.db.commit()
            output = {"decoded_transactions": len(txs), "evidence_count": len(evidence_ids)}
            job_service.finish(job, "success", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="success", summary=output, evidence_ids=evidence_ids)
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, evidence_ids=evidence_ids, error=str(exc))

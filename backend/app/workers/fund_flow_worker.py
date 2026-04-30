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
            edges: list[dict] = []
            for tx in txs:
                if tx.value_wei and int(tx.value_wei) > 0:
                    edge = {
                        "from": tx.from_address,
                        "to": tx.to_address,
                        "asset": "native",
                        "amount": str(tx.value_wei),
                        "amount_raw": str(tx.value_wei),
                        "tx_hash": tx.tx_hash,
                        "confidence": "high",
                    }
                    evidence = EvidenceService(self.db).create_evidence(
                        case_id=case_id,
                        tx_id=tx.id,
                        source_type="balance_diff",
                        producer=self.name,
                        claim_key="native_value_transfer",
                        raw_path=None,
                        decoded=edge,
                        confidence="high",
                    )
                    evidence_ids.append(evidence.id)
                    edges.append(edge)
            transfer_logs = [
                item
                for item in EvidenceService(self.db).list_for_case(case_id)
                if (
                    item.source_type == "receipt_log"
                    and (
                        str(item.decoded.get("event", "")).lower() == "transfer"
                        or item.claim_key in {"evm_receipt_events_normalized", "revert_receipt_flow_summary"}
                    )
                )
                or (item.source_type == "balance_diff" and item.claim_key == "sui_reward_redemption_flow")
            ]
            for item in transfer_logs:
                decoded = item.decoded or {}
                candidate_edges = decoded.get("fund_flow_edges") or decoded.get("token_transfers") or decoded.get("flows") or []
                if isinstance(candidate_edges, list):
                    for edge in candidate_edges:
                        if isinstance(edge, dict) and (edge.get("from") or edge.get("to")):
                            edges.append({**edge, "evidence_id": item.id, "confidence": edge.get("confidence") or item.confidence})
            evidence_ids.extend(item.id for item in transfer_logs)
            if edges:
                flow_evidence = EvidenceService(self.db).create_evidence(
                    case_id=case_id,
                    tx_id=None,
                    source_type="balance_diff",
                    producer=self.name,
                    claim_key="fund_flow_edges",
                    raw_path=None,
                    decoded={"fund_flow_edges": edges, "edge_count": len(edges)},
                    confidence="high",
                )
                evidence_ids.append(flow_evidence.id)
            if evidence_ids:
                existing = next((item for item in FindingService(self.db).list_for_case(case_id) if item.finding_type == "fund_flow"), None)
                if existing is None:
                    finding = FindingService(self.db).create_finding(
                        case_id,
                        FindingCreate(
                            title="Asset movement evidence detected",
                            finding_type="fund_flow",
                            severity="high",
                            confidence="high",
                            claim=f"Detected {len(edges) or len(evidence_ids)} native/token transfer evidence item(s).",
                            rationale="Transfer logs and native value movement are deterministic fund-flow evidence.",
                            falsification="USD valuation and cross-chain destination confirmation remain separate checks.",
                            evidence_ids=evidence_ids,
                            created_by=self.name,
                        ),
                    )
                    finding_ids.append(finding.id)
                else:
                    finding_ids.append(existing.id)
            output = {"fund_flow_evidence_count": len(evidence_ids), "fund_flow_edge_count": len(edges), "finding_ids": finding_ids}
            job_service.finish(job, "success" if evidence_ids else "partial", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="success" if evidence_ids else "partial", summary=output, evidence_ids=evidence_ids)
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, evidence_ids=evidence_ids, error=str(exc))

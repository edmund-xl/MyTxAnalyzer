from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import WorkerResult
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.job_service import JobService

STABLECOIN_SYMBOLS = {"USDC", "USDT", "DAI", "USD", "USDT0", "USDm", "xUSD"}
STABLECOIN_ADDRESSES = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
}


class LossCalculatorWorker:
    name = "loss_calculator_worker"

    def __init__(self, db: Session) -> None:
        self.db = db

    def run(self, case_id: str) -> WorkerResult:
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {})
        try:
            case = CaseService(self.db).get_case(case_id)
            fund_evidence = [
                item
                for item in EvidenceService(self.db).list_for_case(case_id)
                if item.source_type in {"balance_diff", "receipt_log"}
                and item.claim_key in {"native_value_transfer", "transfer", "sui_reward_redemption_flow", "fund_flow_edges", "evm_receipt_events_normalized", "revert_receipt_flow_summary"}
            ]
            edges = []
            for item in fund_evidence:
                decoded = item.decoded or {}
                values = decoded.get("fund_flow_edges") or decoded.get("token_transfers") or decoded.get("flows") or []
                if isinstance(values, list):
                    edges.extend(edge for edge in values if isinstance(edge, dict))
            stablecoin_total = 0.0
            stablecoin_rows = []
            for edge in edges:
                amount = self._stablecoin_amount(edge)
                if amount is None:
                    continue
                stablecoin_total += amount
                stablecoin_rows.append(
                    {
                        "asset": edge.get("asset"),
                        "amount": amount,
                        "from": edge.get("from"),
                        "to": edge.get("to"),
                        "tx_hash": edge.get("tx_hash"),
                    }
                )
            usd_loss = float(case.loss_usd) if case.loss_usd is not None else (stablecoin_total if stablecoin_total else None)
            confidence = "medium" if usd_loss is not None else "partial"
            reason = (
                "Stablecoin-denominated flow used as direct USD estimate."
                if stablecoin_total
                else "No price source configured; token-denominated evidence retained."
            )
            evidence = EvidenceService(self.db).create_evidence(
                case_id=case_id,
                source_type="artifact_summary",
                producer=self.name,
                claim_key="loss_calculation_status",
                raw_path=None,
                decoded={
                    "fund_flow_evidence_count": len(fund_evidence),
                    "fund_flow_edge_count": len(edges),
                    "usd_loss": usd_loss,
                    "stablecoin_estimate_usd": stablecoin_total or None,
                    "stablecoin_rows": stablecoin_rows[:100],
                    "reason": reason,
                },
                confidence=confidence,
            )
            output = {"fund_flow_evidence_count": len(fund_evidence), "fund_flow_edge_count": len(edges), "usd_loss": usd_loss}
            job_service.finish(job, "success" if usd_loss is not None else "partial", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="success" if usd_loss is not None else "partial", summary=output, evidence_ids=[evidence.id])
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, error=str(exc))

    def _stablecoin_amount(self, edge: dict) -> float | None:
        asset = str(edge.get("asset") or edge.get("token") or "").strip()
        asset_key = asset.upper()
        if asset_key.startswith("0X"):
            asset_key = asset.lower()
        if asset_key not in STABLECOIN_SYMBOLS and asset_key not in STABLECOIN_ADDRESSES:
            return None
        raw = str(edge.get("amount_raw") or edge.get("amount") or "")
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            return None
        if asset_key in STABLECOIN_ADDRESSES and value > 1_000_000:
            return value / 1_000_000
        return value

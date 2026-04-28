from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db import AuditLog, Case, DiagramSpec, Evidence, Finding, JobRun, Report, Transaction, utcnow
from app.models.schemas import CaseCreate, TransactionCreate
from app.services.network_service import NetworkService


class CaseService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_case(self, payload: CaseCreate, created_by: str | None = None) -> Case:
        network = NetworkService(self.db).get_network(payload.network_key)
        if network is None:
            raise HTTPException(status_code=422, detail=f"Network {payload.network_key} is not configured")
        case = Case(
            title=payload.title or self._default_title(payload),
            network_key=payload.network_key,
            seed_type=payload.seed_type.value,
            seed_value=payload.seed_value,
            time_window_hours=payload.time_window_hours,
            depth=payload.depth.value,
            language=payload.language,
            created_by=created_by,
        )
        self.db.add(case)
        self.db.flush()
        self.db.add(
            AuditLog(
                case_id=case.id,
                actor=created_by,
                action="case.created",
                target_type="case",
                target_id=case.id,
                metadata_json={"seed_type": case.seed_type, "network_key": case.network_key},
            )
        )
        self.db.commit()
        self.db.refresh(case)
        return case

    def list_cases(self, status: str | None = None, network_key: str | None = None, limit: int = 50, offset: int = 0) -> list[Case]:
        query = select(Case)
        if status:
            query = query.where(Case.status == status)
        if network_key:
            query = query.where(Case.network_key == network_key)
        return list(self.db.scalars(query.order_by(Case.updated_at.desc()).offset(offset).limit(limit)).all())

    def summary(self) -> dict:
        by_status = {
            str(status): int(count)
            for status, count in self.db.execute(select(Case.status, func.count(Case.id)).group_by(Case.status)).all()
        }
        by_severity = {
            str(severity): int(count)
            for severity, count in self.db.execute(select(Case.severity, func.count(Case.id)).group_by(Case.severity)).all()
        }
        total = int(self.db.scalar(select(func.count(Case.id))) or 0)
        review_queue_statuses = {"REPORT_DRAFTED", "UNDER_REVIEW", "PARTIAL"}
        return {
            "total_cases": total,
            "by_status": by_status,
            "by_severity": by_severity,
            "review_queue": sum(by_status.get(status, 0) for status in review_queue_statuses),
            "high_severity": sum(by_severity.get(severity, 0) for severity in {"critical", "high"}),
        }

    def detail_summary(self, case_id: str) -> dict:
        self.get_case(case_id)
        return {
            "transaction_count": int(self.db.scalar(select(func.count(Transaction.id)).where(Transaction.case_id == case_id)) or 0),
            "evidence_count": int(self.db.scalar(select(func.count(Evidence.id)).where(Evidence.case_id == case_id)) or 0),
            "finding_count": int(self.db.scalar(select(func.count(Finding.id)).where(Finding.case_id == case_id)) or 0),
            "report_count": int(self.db.scalar(select(func.count(Report.id)).where(Report.case_id == case_id)) or 0),
            "diagram_count": int(self.db.scalar(select(func.count(DiagramSpec.id)).where(DiagramSpec.case_id == case_id)) or 0),
            "job_count": int(self.db.scalar(select(func.count(JobRun.id)).where(JobRun.case_id == case_id)) or 0),
        }

    def get_case(self, case_id: str) -> Case:
        case = self.db.get(Case, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return case

    def update_status(self, case_id: str, status: str) -> Case:
        case = self.get_case(case_id)
        case.status = status
        case.updated_at = utcnow()
        self.db.add(case)
        self.db.commit()
        self.db.refresh(case)
        return case

    def add_transaction(self, case_id: str, payload: TransactionCreate) -> Transaction:
        case = self.get_case(case_id)
        tx_hash = payload.tx_hash.lower() if getattr(case.network, "network_type", "evm") == "evm" and payload.tx_hash.startswith("0x") else payload.tx_hash
        tx = self.db.scalar(select(Transaction).where(Transaction.case_id == case_id, Transaction.tx_hash == tx_hash))
        if tx is None:
            tx = Transaction(case_id=case_id, tx_hash=tx_hash, phase=payload.phase, metadata_json=payload.metadata)
        else:
            tx.phase = payload.phase or tx.phase
            tx.metadata_json = {**(tx.metadata_json or {}), **payload.metadata}
        if tx_hash.startswith("0x") and len(tx_hash) >= 10:
            tx.method_selector = payload.metadata.get("method_selector") or tx.method_selector
        self.db.add(tx)
        self.db.commit()
        self.db.refresh(tx)
        return tx

    def list_transactions(self, case_id: str, limit: int = 10000, offset: int = 0) -> list[Transaction]:
        self.get_case(case_id)
        query = (
            select(Transaction)
            .where(Transaction.case_id == case_id)
            .order_by(Transaction.block_number.is_(None), Transaction.block_number, Transaction.created_at)
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(query).all())

    def timeline(self, case_id: str, limit: int = 10000, offset: int = 0) -> list[dict]:
        self.get_case(case_id)
        evidence_counts = dict(
            self.db.execute(
                select(Evidence.tx_id, func.count(Evidence.id)).where(Evidence.case_id == case_id).group_by(Evidence.tx_id)
            ).all()
        )
        rows = self.list_transactions(case_id, limit=limit, offset=offset)
        return [
            {
                "tx_id": tx.id,
                "tx_hash": tx.tx_hash,
                "timestamp": tx.block_timestamp,
                "block_number": tx.block_number,
                "phase": tx.phase,
                "from_address": tx.from_address,
                "to_address": tx.to_address,
                "method": tx.method_name or tx.method_selector,
                "confidence": tx.phase_confidence,
                "evidence_count": int(evidence_counts.get(tx.id, 0)),
            }
            for tx in rows
        ]

    def _default_title(self, payload: CaseCreate) -> str:
        short_seed = payload.seed_value[:12] + "..." if len(payload.seed_value) > 16 else payload.seed_value
        return f"{payload.network_key} {payload.seed_type.value} {short_seed}"

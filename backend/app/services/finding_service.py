from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import Finding, FindingEvidence, utcnow
from app.models.schemas import FindingCreate, FindingReviewRequest
from app.services.evidence_service import EvidenceService


class FindingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.evidence_service = EvidenceService(db)

    def list_for_case(self, case_id: str, limit: int = 10000, offset: int = 0) -> list[Finding]:
        query = (
            select(Finding)
            .where(Finding.case_id == case_id)
            .order_by(Finding.created_at, Finding.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(query).all())

    def get(self, finding_id: str) -> Finding | None:
        return self.db.get(Finding, finding_id)

    def create_finding(self, case_id: str, payload: FindingCreate) -> Finding:
        if payload.confidence == "high" and not self.evidence_service.has_deterministic_evidence(payload.evidence_ids):
            raise HTTPException(status_code=422, detail="High-confidence findings require deterministic evidence")
        finding = Finding(case_id=case_id, **payload.model_dump())
        self.db.add(finding)
        self.db.commit()
        self.db.refresh(finding)
        for evidence_id in payload.evidence_ids:
            self.db.merge(FindingEvidence(finding_id=finding.id, evidence_id=evidence_id))
        self.db.commit()
        return finding

    def review(self, finding_id: str, payload: FindingReviewRequest) -> Finding:
        finding = self.get(finding_id)
        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found")
        new_confidence = payload.confidence or finding.confidence
        if new_confidence == "high" and not self.evidence_service.has_deterministic_evidence(finding.evidence_ids):
            raise HTTPException(status_code=422, detail="High-confidence findings require deterministic evidence")
        finding.reviewer_status = payload.reviewer_status.value
        finding.reviewer_comment = payload.reviewer_comment
        finding.confidence = new_confidence.value if hasattr(new_confidence, "value") else str(new_confidence)
        finding.updated_at = utcnow()
        self.db.add(finding)
        self.db.commit()
        self.db.refresh(finding)
        return finding

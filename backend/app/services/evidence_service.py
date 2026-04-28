from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import Artifact, Evidence

DETERMINISTIC_EVIDENCE_TYPES = {
    "receipt_log",
    "trace_call",
    "source_line",
    "state_call",
    "signature",
    "balance_diff",
    "tx_metadata",
}


class EvidenceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_case(self, case_id: str, limit: int = 10000, offset: int = 0) -> list[Evidence]:
        query = (
            select(Evidence)
            .where(Evidence.case_id == case_id)
            .order_by(Evidence.created_at, Evidence.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(query).all())

    def get(self, evidence_id: str) -> Evidence | None:
        return self.db.get(Evidence, evidence_id)

    def create_evidence(
        self,
        case_id: str,
        source_type: str,
        producer: str,
        claim_key: str,
        raw_path: str | None,
        decoded: dict,
        confidence: str,
        tx_id: str | None = None,
    ) -> Evidence:
        existing = self.db.scalar(
            select(Evidence).where(
                Evidence.case_id == case_id,
                Evidence.source_type == source_type,
                Evidence.producer == producer,
                Evidence.claim_key == claim_key,
                Evidence.raw_path == raw_path,
            )
        )
        if existing:
            existing.decoded = decoded
            existing.confidence = confidence
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing

        evidence = Evidence(
            case_id=case_id,
            tx_id=tx_id,
            source_type=source_type,
            producer=producer,
            claim_key=claim_key,
            raw_path=raw_path,
            decoded=decoded,
            confidence=confidence,
        )
        self.db.add(evidence)
        self.db.commit()
        self.db.refresh(evidence)
        return evidence

    def create_artifact(
        self,
        case_id: str,
        producer: str,
        artifact_type: str,
        object_path: str,
        content_hash: str | None = None,
        size_bytes: int | None = None,
        metadata: dict | None = None,
        tx_id: str | None = None,
    ) -> Artifact:
        existing = self.db.scalar(select(Artifact).where(Artifact.case_id == case_id, Artifact.object_path == object_path))
        if existing:
            existing.content_hash = content_hash
            existing.size_bytes = size_bytes
            existing.metadata_json = metadata or {}
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        artifact = Artifact(
            case_id=case_id,
            tx_id=tx_id,
            producer=producer,
            artifact_type=artifact_type,
            object_path=object_path,
            content_hash=content_hash,
            size_bytes=size_bytes,
            metadata_json=metadata or {},
        )
        self.db.add(artifact)
        self.db.commit()
        self.db.refresh(artifact)
        return artifact

    def has_deterministic_evidence(self, evidence_ids: list[str]) -> bool:
        if not evidence_ids:
            return False
        rows = self.db.scalars(select(Evidence).where(Evidence.id.in_(evidence_ids))).all()
        return any(row.source_type in DETERMINISTIC_EVIDENCE_TYPES for row in rows)

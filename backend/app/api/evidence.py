from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Actor, get_actor, require_capability
from app.models.schemas import EvidenceResponse
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService

router = APIRouter()


@router.get("/cases/{case_id}/evidence", response_model=list[EvidenceResponse])
def list_case_evidence(
    case_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
):
    require_capability(actor, "read")
    CaseService(db).get_case(case_id)
    return EvidenceService(db).list_for_case(case_id, limit=limit, offset=offset)


@router.get("/evidence/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(evidence_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    evidence = EvidenceService(db).get(evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return evidence

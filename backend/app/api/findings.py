from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Actor, get_actor, require_capability
from app.models.schemas import FindingResponse, FindingReviewRequest
from app.services.case_service import CaseService
from app.services.finding_service import FindingService

router = APIRouter()


@router.get("/cases/{case_id}/findings", response_model=list[FindingResponse])
def list_findings(
    case_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
):
    require_capability(actor, "read")
    CaseService(db).get_case(case_id)
    return FindingService(db).list_for_case(case_id, limit=limit, offset=offset)


@router.patch("/findings/{finding_id}/review", response_model=FindingResponse)
def review_finding(finding_id: str, payload: FindingReviewRequest, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "review")
    return FindingService(db).review(finding_id, payload)

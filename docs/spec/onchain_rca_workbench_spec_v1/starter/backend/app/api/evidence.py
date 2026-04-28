from fastapi import APIRouter
from uuid import UUID

router = APIRouter()

@router.get("/cases/{case_id}/evidence")
def list_evidence(case_id: UUID):
    # TODO: EvidenceService.list_by_case
    return []

@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: UUID):
    # TODO: EvidenceService.get
    return {}

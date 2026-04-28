from fastapi import APIRouter
from uuid import UUID

router = APIRouter()

@router.get("/cases/{case_id}/findings")
def list_findings(case_id: UUID):
    # TODO: FindingService.list_by_case
    return []

@router.patch("/findings/{finding_id}/review")
def review_finding(finding_id: UUID, payload: dict):
    # TODO: FindingService.review
    return {"id": str(finding_id), "review": payload}

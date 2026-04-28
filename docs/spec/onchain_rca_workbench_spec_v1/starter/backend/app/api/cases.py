from fastapi import APIRouter, HTTPException
from uuid import UUID

from app.models.schemas import CaseCreate, CaseResponse

router = APIRouter()

@router.post("", response_model=CaseResponse, status_code=201)
def create_case(payload: CaseCreate) -> CaseResponse:
    # TODO: call CaseService.create_case
    return CaseResponse.mock_from_create(payload)

@router.get("")
def list_cases():
    # TODO: call CaseService.list_cases
    return []

@router.get("/{case_id}")
def get_case(case_id: UUID):
    # TODO: call CaseService.get_case
    raise HTTPException(status_code=404, detail="Not implemented")

@router.post("/{case_id}/run", status_code=202)
def run_case(case_id: UUID):
    # TODO: start Temporal workflow
    return {"workflow_id": f"case-{case_id}", "status": "started"}

@router.get("/{case_id}/timeline")
def get_timeline(case_id: UUID):
    # TODO: return timeline items
    return []

from fastapi import APIRouter
from uuid import UUID

router = APIRouter()

@router.post("/cases/{case_id}/reports", status_code=201)
def generate_report(case_id: UUID, payload: dict | None = None):
    # TODO: ReportService.generate
    return {"case_id": str(case_id), "status": "draft"}

@router.get("/cases/{case_id}/reports")
def list_reports(case_id: UUID):
    return []

@router.get("/cases/{case_id}/reports/{report_id}")
def get_report(case_id: UUID, report_id: UUID):
    return {"case_id": str(case_id), "report_id": str(report_id)}

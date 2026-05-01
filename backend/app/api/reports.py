from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Actor, get_actor, require_capability
from app.models.report_quality import ClaimGraph, ReportQualityResult
from app.models.schemas import DiagramSpecResponse, JobRunResponse, ReportCreate, ReportDetail, ReportExportCreate, ReportExportResponse, ReportResponse
from app.services.case_service import CaseService
from app.services.diagram_service import DiagramService
from app.services.job_service import JobService
from app.services.report_export_service import ReportExportService
from app.services.report_quality_service import ReportQualityService
from app.services.report_service import ReportService

router = APIRouter()


@router.post("/cases/{case_id}/reports", response_model=ReportResponse, status_code=201)
def create_report(case_id: str, payload: ReportCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "run")
    CaseService(db).get_case(case_id)
    return ReportService(db).create_report(case_id, language=payload.language, report_format=payload.format, created_by=actor.user_id)


@router.get("/cases/{case_id}/reports", response_model=list[ReportResponse])
def list_reports(
    case_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
):
    require_capability(actor, "read")
    CaseService(db).get_case(case_id)
    return ReportService(db).list_for_case(case_id, limit=limit, offset=offset)


@router.get("/cases/{case_id}/reports/{report_id}", response_model=ReportDetail)
def get_report(case_id: str, report_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    CaseService(db).get_case(case_id)
    report = ReportService(db).get(report_id)
    if report is None or report.case_id != case_id:
        raise HTTPException(status_code=404, detail="Report not found")
    detail = ReportDetail.model_validate(report)
    detail.content = ReportService(db).get_content(report)
    return detail


@router.post("/reports/{report_id}/publish", response_model=ReportResponse)
def publish_report(report_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "publish")
    return ReportService(db).publish(report_id, actor.user_id)


@router.get("/reports/{report_id}/claims", response_model=ClaimGraph)
def get_report_claims(report_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    report = ReportService(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportQualityService(db).load_claim_graph(report)


@router.get("/reports/{report_id}/quality", response_model=ReportQualityResult)
def get_report_quality(report_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    report = ReportService(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportQualityService(db).load_quality_result(report)


@router.get("/cases/{case_id}/diagrams", response_model=list[DiagramSpecResponse])
def list_diagrams(case_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    CaseService(db).get_case(case_id)
    return DiagramService(db).list_for_case(case_id)


@router.post("/reports/{report_id}/exports", response_model=ReportExportResponse, status_code=201)
def create_report_export(report_id: str, payload: ReportExportCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "run")
    export, should_run = ReportExportService(db).request_export_job(report_id, payload.format, actor.user_id)
    if should_run:
        background_tasks.add_task(ReportExportService.run_export_background, export.id)
    return export


@router.get("/reports/{report_id}/exports", response_model=list[ReportExportResponse])
def list_report_exports(report_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    report = ReportService(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportExportService(db).list_for_report(report_id)


@router.get("/report-exports/{export_id}/download")
def download_report_export(export_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    export, content = ReportExportService(db).download_bytes(export_id)
    return StreamingResponse(
        iter([content]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-{export.report_id}.pdf"'},
    )


@router.get("/cases/{case_id}/jobs", response_model=list[JobRunResponse])
def list_jobs(
    case_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
):
    require_capability(actor, "read")
    CaseService(db).get_case(case_id)
    return JobService(db).list_for_case(case_id, limit=limit, offset=offset)

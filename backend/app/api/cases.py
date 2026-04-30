from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from temporalio.client import Client

from app.core.config import settings
from app.core.database import get_db
from app.core.security import Actor, get_actor, require_capability
from app.models.schemas import CaseCreate, CaseDetailSummaryResponse, CaseResponse, CaseSummaryResponse, RunCaseResponse, TimelineItem, TransactionCreate, TransactionResponse, WorkflowRunResponse
from app.services.case_service import CaseService
from app.services.workflow_run_service import WorkflowRunService
from app.workflows.case_analysis_workflow import CaseAnalysisWorkflow
from app.workflows.case_runner import InlineCaseRunner

router = APIRouter()


@router.post("", response_model=CaseResponse, status_code=201)
def create_case(payload: CaseCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "create")
    return CaseService(db).create_case(payload, actor.user_id)


@router.get("", response_model=list[CaseResponse])
def list_cases(
    status: str | None = Query(default=None),
    network_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
):
    require_capability(actor, "read")
    return CaseService(db).list_cases(status=status, network_key=network_key, limit=limit, offset=offset)


@router.get("/summary", response_model=CaseSummaryResponse)
def case_summary(db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    return CaseService(db).summary()


@router.get("/{case_id}/summary", response_model=CaseDetailSummaryResponse)
def case_detail_summary(case_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    return CaseService(db).detail_summary(case_id)


@router.get("/{case_id}", response_model=CaseResponse)
def get_case(case_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "read")
    return CaseService(db).get_case(case_id)


@router.post("/{case_id}/run", response_model=RunCaseResponse, status_code=202)
async def run_case(case_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "run")
    CaseService(db).get_case(case_id)
    workflow_id = f"case-{case_id}-{uuid4()}"
    if settings.workflow_mode == "temporal":
        workflow_run = WorkflowRunService(db).start(case_id, workflow_id, "temporal", {"actor": actor.user_id})
        client = await Client.connect(settings.temporal_address)
        await client.start_workflow(CaseAnalysisWorkflow.run, case_id, workflow_run.id, id=workflow_id, task_queue="case-analysis")
        return RunCaseResponse(workflow_id=workflow_id, workflow_run_id=workflow_run.id, status="started", mode="temporal")
    result = InlineCaseRunner(db).run(case_id, workflow_id=workflow_id)
    return RunCaseResponse(workflow_id=workflow_id, workflow_run_id=result.get("workflow_run_id"), status=result["status"], mode="inline")


@router.get("/{case_id}/workflow-runs", response_model=list[WorkflowRunResponse])
def list_workflow_runs(
    case_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
):
    require_capability(actor, "read")
    CaseService(db).get_case(case_id)
    return WorkflowRunService(db).list_for_case(case_id, limit=limit, offset=offset)


@router.post("/workflow-runs/{workflow_run_id}/cancel", response_model=WorkflowRunResponse)
def cancel_workflow_run(workflow_run_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "run")
    row = WorkflowRunService(db).cancel(workflow_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return row


@router.get("/{case_id}/transactions", response_model=list[TransactionResponse])
def list_transactions(
    case_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
):
    require_capability(actor, "read")
    return CaseService(db).list_transactions(case_id, limit=limit, offset=offset)


@router.post("/{case_id}/transactions", response_model=TransactionResponse, status_code=201)
def add_transaction(case_id: str, payload: TransactionCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    require_capability(actor, "run")
    return CaseService(db).add_transaction(case_id, payload)


@router.get("/{case_id}/timeline", response_model=list[TimelineItem])
def get_timeline(
    case_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
):
    require_capability(actor, "read")
    return CaseService(db).timeline(case_id, limit=limit, offset=offset)

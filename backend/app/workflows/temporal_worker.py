from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio import activity
from temporalio.worker import Worker

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schemas import CaseStatus
from app.services.case_service import CaseService
from app.services.job_service import current_workflow_run_id
from app.services.workflow_run_service import WorkflowRunService
from app.workers.acl_forensics_worker import ACLForensicsWorker
from app.workers.decode_worker import DecodeWorker
from app.workers.environment_check_worker import EnvironmentCheckWorker
from app.workers.fund_flow_worker import FundFlowWorker
from app.workers.loss_calculator_worker import LossCalculatorWorker
from app.workers.rca_agent_worker import RCAAgentWorker
from app.workers.report_worker import ReportWorker
from app.workers.safe_forensics_worker import SafeForensicsWorker
from app.workers.tx_discovery_worker import TxDiscoveryWorker
from app.workers.txanalyzer_worker import TxAnalyzerJobInput, TxAnalyzerWorker
from app.workflows.case_analysis_workflow import CaseAnalysisWorkflow
from app.workflows.case_runner import InlineCaseRunner


@activity.defn(name="run_case_inline_activity")
async def run_case_inline_activity(case_id: str) -> dict:
    db = SessionLocal()
    try:
        return InlineCaseRunner(db).run(case_id)
    finally:
        db.close()


@activity.defn(name="run_case_step_activity")
async def run_case_step_activity(payload: dict) -> dict:
    db = SessionLocal()
    workflow_run_id = payload.get("workflow_run_id")
    token = current_workflow_run_id.set(workflow_run_id)
    try:
        return _run_step(db, payload["case_id"], payload["step"], payload.get("context") or {})
    finally:
        current_workflow_run_id.reset(token)
        db.close()


@activity.defn(name="finalize_case_workflow_activity")
async def finalize_case_workflow_activity(payload: dict) -> dict:
    db = SessionLocal()
    try:
        case_id = payload["case_id"]
        status = payload["status"]
        CaseService(db).update_status(case_id, status)
        workflow_run_id = payload.get("workflow_run_id")
        if workflow_run_id:
            WorkflowRunService(db).finish(workflow_run_id, status, {"step_count": payload.get("step_count")})
        return {"case_id": case_id, "workflow_run_id": workflow_run_id, "status": status}
    finally:
        db.close()


def _run_step(db, case_id: str, step: str, context: dict) -> dict:
    case_service = CaseService(db)
    mapping = {
        "environment_check": (CaseStatus.ENV_CHECKING, EnvironmentCheckWorker(db).run, CaseStatus.ENV_CHECKED),
        "tx_discovery": (CaseStatus.DISCOVERING_TRANSACTIONS, TxDiscoveryWorker(db).run, CaseStatus.TRANSACTIONS_DISCOVERED),
        "decode": (CaseStatus.DECODING, DecodeWorker(db).run, CaseStatus.DECODED),
        "acl_forensics": (CaseStatus.RUNNING_FORENSICS, ACLForensicsWorker(db).run, CaseStatus.FORENSICS_DONE),
        "safe_forensics": (CaseStatus.RUNNING_FORENSICS, SafeForensicsWorker(db).run, CaseStatus.FORENSICS_DONE),
        "fund_flow": (CaseStatus.RUNNING_FORENSICS, FundFlowWorker(db).run, CaseStatus.FORENSICS_DONE),
        "loss_calculation": (CaseStatus.RUNNING_FORENSICS, LossCalculatorWorker(db).run, CaseStatus.FORENSICS_DONE),
        "rca_agent": (CaseStatus.RUNNING_RCA_AGENT, RCAAgentWorker(db).run, CaseStatus.RCA_DONE),
        "report_draft": (CaseStatus.DRAFTING_REPORT, ReportWorker(db).run, CaseStatus.REPORT_DRAFTED),
    }
    if step == "artifact_pull":
        return _run_artifact_pull(db, case_id, context)
    from_status, fn, to_status = mapping[step]
    case_service.update_status(case_id, from_status.value)
    result = fn(case_id)
    data = result.model_dump() if hasattr(result, "model_dump") else result
    if data["status"] != "failed":
        case_service.update_status(case_id, to_status.value)
    return data | {"step": step}


def _run_artifact_pull(db, case_id: str, context: dict) -> dict:
    case_service = CaseService(db)
    case_service.update_status(case_id, CaseStatus.PULLING_ARTIFACTS.value)
    case = case_service.get_case(case_id)
    if getattr(case.network, "network_type", "evm") != "evm":
        result = {
            "case_id": case_id,
            "worker_name": "txanalyzer_worker",
            "status": "partial",
            "summary": {"skipped": True, "reason": f"TxAnalyzer is EVM-only; {case.network.network_type} uses native RPC artifacts."},
            "artifacts": [],
            "evidence_ids": [],
            "step": "artifact_pull",
        }
        case_service.update_status(case_id, CaseStatus.ARTIFACTS_PULLED.value)
        return result
    artifact_failures = 0
    outputs = []
    env_summary = ((context.get("environment") or {}).get("summary") or {})
    for tx in case_service.list_transactions(case_id):
        tx_result = TxAnalyzerWorker(db).run(
            TxAnalyzerJobInput(
                case_id=case_id,
                network_key=case.network_key,
                tx_hash=tx.tx_hash,
                skip_opcode=not bool(env_summary.get("debug_trace_transaction_ok")),
            )
        )
        outputs.append(tx_result.model_dump())
        artifact_failures += 1 if tx_result.status == "failed" else 0
    final = "failed" if artifact_failures else "success"
    case_service.update_status(case_id, CaseStatus.ARTIFACTS_PULLED.value if artifact_failures == 0 else CaseStatus.PARTIAL.value)
    return {"case_id": case_id, "worker_name": "txanalyzer_worker", "status": final, "summary": {"transactions": len(outputs), "failures": artifact_failures}, "artifacts": [], "evidence_ids": [], "step": "artifact_pull", "outputs": outputs}


async def main() -> None:
    client = await Client.connect(settings.temporal_address)
    worker = Worker(
        client,
        task_queue="case-analysis",
        workflows=[CaseAnalysisWorkflow],
        activities=[run_case_inline_activity, run_case_step_activity, finalize_case_workflow_activity],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

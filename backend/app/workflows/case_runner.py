from __future__ import annotations

from sqlalchemy.orm import Session

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


class InlineCaseRunner:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.case_service = CaseService(db)

    def run(self, case_id: str, workflow_id: str | None = None, workflow_run_id: str | None = None) -> dict:
        results: list[dict] = []
        any_failed = False
        workflow_id = workflow_id or f"case-{case_id}"
        workflow_service = WorkflowRunService(self.db)
        workflow_run = workflow_service.start(case_id, workflow_id, "inline", {"runner": "InlineCaseRunner"}) if workflow_run_id is None else None
        active_workflow_run_id = workflow_run_id or (workflow_run.id if workflow_run else None)
        token = current_workflow_run_id.set(active_workflow_run_id)
        try:
            result = self._run_steps(case_id, results, any_failed)
            workflow_service.finish(active_workflow_run_id, result["status"], {"step_count": len(result["steps"])}) if active_workflow_run_id else None
            result["workflow_run_id"] = active_workflow_run_id
            return result
        except Exception as exc:
            workflow_service.finish(active_workflow_run_id, CaseStatus.FAILED.value, error=str(exc)) if active_workflow_run_id else None
            self.case_service.update_status(case_id, CaseStatus.FAILED.value)
            raise
        finally:
            current_workflow_run_id.reset(token)

    def _run_steps(self, case_id: str, results: list[dict], any_failed: bool) -> dict:

        env_result = self._step(case_id, CaseStatus.ENV_CHECKING, EnvironmentCheckWorker(self.db).run, CaseStatus.ENV_CHECKED)
        results.append(env_result)
        if env_result["status"] == "failed":
            any_failed = True

        discovery_result = self._step(case_id, CaseStatus.DISCOVERING_TRANSACTIONS, TxDiscoveryWorker(self.db).run, CaseStatus.TRANSACTIONS_DISCOVERED)
        results.append(discovery_result)
        if discovery_result["status"] == "failed":
            any_failed = True

        self.case_service.update_status(case_id, CaseStatus.PULLING_ARTIFACTS.value)
        artifact_failures = 0
        case = self.case_service.get_case(case_id)
        if getattr(case.network, "network_type", "evm") == "evm":
            for tx in self.case_service.list_transactions(case_id):
                tx_result = TxAnalyzerWorker(self.db).run(
                    TxAnalyzerJobInput(
                        case_id=case_id,
                        network_key=case.network_key,
                        tx_hash=tx.tx_hash,
                        skip_opcode=not bool(env_result.get("summary", {}).get("debug_trace_transaction_ok")),
                    )
                )
                results.append(tx_result.model_dump())
                artifact_failures += 1 if tx_result.status == "failed" else 0
        else:
            results.append(
                {
                    "case_id": case_id,
                    "worker_name": "txanalyzer_worker",
                    "status": "partial",
                    "summary": {"skipped": True, "reason": f"TxAnalyzer is EVM-only; {case.network.network_type} uses native RPC artifacts."},
                    "artifacts": [],
                    "evidence_ids": [],
                }
            )
        self.case_service.update_status(case_id, CaseStatus.ARTIFACTS_PULLED.value if artifact_failures == 0 else CaseStatus.PARTIAL.value)
        any_failed = any_failed or artifact_failures > 0

        for from_status, worker, to_status in [
            (CaseStatus.DECODING, DecodeWorker(self.db).run, CaseStatus.DECODED),
            (CaseStatus.RUNNING_FORENSICS, ACLForensicsWorker(self.db).run, CaseStatus.FORENSICS_DONE),
            (CaseStatus.RUNNING_FORENSICS, SafeForensicsWorker(self.db).run, CaseStatus.FORENSICS_DONE),
            (CaseStatus.RUNNING_FORENSICS, FundFlowWorker(self.db).run, CaseStatus.FORENSICS_DONE),
            (CaseStatus.RUNNING_FORENSICS, LossCalculatorWorker(self.db).run, CaseStatus.FORENSICS_DONE),
            (CaseStatus.RUNNING_RCA_AGENT, RCAAgentWorker(self.db).run, CaseStatus.RCA_DONE),
            (CaseStatus.DRAFTING_REPORT, ReportWorker(self.db).run, CaseStatus.REPORT_DRAFTED),
        ]:
            result = self._step(case_id, from_status, worker, to_status)
            results.append(result)
            any_failed = any_failed or result["status"] == "failed"

        final_status = CaseStatus.PARTIAL.value if any_failed else CaseStatus.REPORT_DRAFTED.value
        self.case_service.update_status(case_id, final_status)
        return {"case_id": case_id, "status": final_status, "steps": results}

    def _step(self, case_id: str, from_status: CaseStatus, fn, to_status: CaseStatus) -> dict:
        self.case_service.update_status(case_id, from_status.value)
        result = fn(case_id)
        data = result.model_dump() if hasattr(result, "model_dump") else result
        if data["status"] != "failed":
            self.case_service.update_status(case_id, to_status.value)
        return data

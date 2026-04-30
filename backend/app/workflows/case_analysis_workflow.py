from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class CaseAnalysisWorkflow:
    @workflow.run
    async def run(self, case_id: str, workflow_run_id: str | None = None) -> dict:
        results: list[dict] = []
        env_result = await self._step(case_id, workflow_run_id, "environment_check", {})
        results.append(env_result)
        for step in [
            "tx_discovery",
            "artifact_pull",
            "decode",
            "acl_forensics",
            "safe_forensics",
            "fund_flow",
            "loss_calculation",
            "rca_agent",
            "report_draft",
        ]:
            result = await self._step(case_id, workflow_run_id, step, {"environment": env_result})
            results.append(result)
        any_failed = any(item.get("status") == "failed" for item in results)
        final_status = "PARTIAL" if any_failed else "REPORT_DRAFTED"
        await workflow.execute_activity(
            "finalize_case_workflow_activity",
            {"case_id": case_id, "workflow_run_id": workflow_run_id, "status": final_status, "step_count": len(results)},
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return {"case_id": case_id, "workflow_run_id": workflow_run_id, "status": final_status, "steps": results}

    async def _step(self, case_id: str, workflow_run_id: str | None, step: str, context: dict) -> dict:
        return await workflow.execute_activity(
            "run_case_step_activity",
            {"case_id": case_id, "workflow_run_id": workflow_run_id, "step": step, "context": context},
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

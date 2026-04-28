from __future__ import annotations

from datetime import timedelta

from temporalio import workflow


@workflow.defn
class CaseAnalysisWorkflow:
    @workflow.run
    async def run(self, case_id: str) -> dict:
        # Activities are implemented by the worker process. The API can also use
        # InlineCaseRunner in development when Temporal is unavailable.
        result = await workflow.execute_activity(
            "run_case_inline_activity",
            case_id,
            start_to_close_timeout=timedelta(minutes=30),
        )
        return result

from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio import activity
from temporalio.worker import Worker

from app.core.config import settings
from app.core.database import SessionLocal
from app.workflows.case_analysis_workflow import CaseAnalysisWorkflow
from app.workflows.case_runner import InlineCaseRunner


@activity.defn(name="run_case_inline_activity")
async def run_case_inline_activity(case_id: str) -> dict:
    db = SessionLocal()
    try:
        return InlineCaseRunner(db).run(case_id)
    finally:
        db.close()


async def main() -> None:
    client = await Client.connect(settings.temporal_address)
    worker = Worker(
        client,
        task_queue="case-analysis",
        workflows=[CaseAnalysisWorkflow],
        activities=[run_case_inline_activity],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

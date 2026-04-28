"""Temporal workflow skeleton.

Codex should implement Temporal activities and wire them to worker classes.
"""

class CaseAnalysisWorkflow:
    async def run(self, case_id: str) -> dict:
        # TODO: implement according to docs/04_WORKFLOW_AND_STATE_MACHINE.md
        return {"case_id": case_id, "status": "not_implemented"}

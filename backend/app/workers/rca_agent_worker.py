from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.object_store import ObjectStore
from app.models.schemas import FindingCreate, WorkerResult
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService
from app.services.job_service import JobService


class RCAAgentWorker:
    name = "rca_agent_worker"

    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def run(self, case_id: str) -> WorkerResult:
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {})
        try:
            case = CaseService(self.db).get_case(case_id)
            evidence = EvidenceService(self.db).list_for_case(case_id)
            findings = FindingService(self.db).list_for_case(case_id)
            if not findings and evidence:
                deterministic = [item.id for item in evidence if item.source_type != "agent_inference"]
                if self._address_seed_without_scope(case, evidence):
                    FindingService(self.db).create_finding(
                        case_id,
                        FindingCreate(
                            title="Address seed did not produce a transaction scope",
                            finding_type="evidence_boundary",
                            severity="info",
                            confidence="partial",
                            claim="The address seed was recorded, but no transaction list, receipt log, or fund-flow evidence was collected for this case.",
                            rationale="Address-based RCA requires an explorer txlist API key or a concrete seed transaction. The current public RPC fallback can verify the network, but it cannot enumerate address history.",
                            falsification="Provide a seed transaction hash or configure the network explorer API key, then rerun discovery and TxAnalyzer.",
                            evidence_ids=deterministic[:5],
                            requires_reviewer=True,
                            created_by=self.name,
                        ),
                    )
                else:
                    FindingService(self.db).create_finding(
                        case_id,
                        FindingCreate(
                            title="Evidence-backed RCA draft requires reviewer analysis",
                            finding_type="data_quality",
                            severity="info",
                            confidence="medium",
                            claim="The system collected evidence but did not identify a specialized high-risk RCA finding automatically.",
                            rationale="This local RCA worker avoids unsupported conclusions when only generic evidence is available.",
                            falsification="Run ACL/Safe/FundFlow modules with complete artifacts to raise confidence.",
                            evidence_ids=deterministic[:5],
                            requires_reviewer=True,
                            created_by=self.name,
                        ),
                    )
            refreshed_findings = FindingService(self.db).list_for_case(case_id)
            root = self._root_cause(refreshed_findings)
            case.root_cause_one_liner = root
            case.attack_type = self._attack_type(refreshed_findings)
            case.severity = self._severity(refreshed_findings)
            case.confidence = self._confidence(refreshed_findings)
            self.db.add(case)
            self.db.commit()
            output = {
                "root_cause_one_liner": root,
                "attack_type": case.attack_type,
                "severity": case.severity,
                "confidence": case.confidence,
                "finding_count": len(refreshed_findings),
                "blockers": [],
                "open_questions": [] if evidence else ["No evidence rows available"],
            }
            content = json.dumps(output, indent=2, ensure_ascii=False).encode("utf-8")
            artifact_uri = self.object_store.put_bytes(content, f"cases/{case_id}/agent/rca_agent_output.json", "application/json")
            EvidenceService(self.db).create_artifact(case_id, self.name, "agent_output", artifact_uri, self.object_store.sha256_bytes(content), len(content))
            job_service.finish(job, "success", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="success", summary=output, artifacts=[artifact_uri])
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, error=str(exc))

    def _root_cause(self, findings) -> str:
        if any(f.finding_type == "evidence_boundary" for f in findings):
            return "Address seed did not produce a transaction scope; no attack root cause is established from the current evidence."
        if any(f.finding_type == "revert_collateralized_position_solvency_check_missing" for f in findings):
            return "Revert Finance evidence indicates a missing solvency constraint in the staking/management path allowed collateralized LP NFT liquidity to be withdrawn while debt remained outstanding."
        if any(f.finding_type == "scallop_deprecated_reward_contract" for f in findings):
            return "Scallop incident evidence points to a deprecated Sui rewards contract path that allowed abnormal sSUI spool reward redemption."
        if any(f.finding_type == "purrlend_unbacked_mint_control_failure" for f in findings):
            return "Purrlend MegaETH evidence indicates an unbacked mint cap / borrow control failure enabled the attacker to extract real assets."
        if any(f.finding_type == "access_control" for f in findings):
            return "Evidence indicates an access-control authorization path is central to the incident; reviewer confirmation is required before publication."
        if any(f.finding_type == "multisig" for f in findings):
            return "Evidence indicates a multisig execution path is relevant; signer attribution requires reviewer validation."
        if any(f.finding_type == "fund_flow" for f in findings):
            return "Evidence confirms asset movement; root cause still requires permission/source/trace correlation."
        return "No high-confidence root cause has been established from available evidence."

    def _attack_type(self, findings) -> str | None:
        if any(f.finding_type == "evidence_boundary" for f in findings):
            return "address_scope_boundary"
        if any(f.finding_type == "revert_collateralized_position_solvency_check_missing" for f in findings):
            return "collateralized_lp_position_solvency_check_missing"
        if any(f.finding_type == "scallop_deprecated_reward_contract" for f in findings):
            return "deprecated_reward_contract_reward_accounting"
        if any(f.finding_type == "purrlend_unbacked_mint_control_failure" for f in findings):
            return "unbacked_mint_borrow_control_failure"
        if any(f.finding_type == "access_control" for f in findings):
            return "access_control_abuse"
        if any(f.finding_type == "multisig" for f in findings):
            return "multisig_authorization"
        if any(f.finding_type == "fund_flow" for f in findings):
            return "fund_flow"
        return None

    def _severity(self, findings) -> str:
        order = ["critical", "high", "medium", "low", "info", "unknown"]
        severities = [f.severity for f in findings]
        for severity in order:
            if severity in severities:
                return severity
        return "unknown"

    def _confidence(self, findings) -> str:
        order = ["high", "medium", "partial", "low"]
        confidences = [f.confidence for f in findings]
        for confidence in order:
            if confidence in confidences:
                return confidence
        return "low"

    def _address_seed_without_scope(self, case, evidence) -> bool:
        return case.seed_type == "address" and any(item.claim_key == "address_discovery_explorer_missing" for item in evidence)

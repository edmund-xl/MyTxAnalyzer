from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.object_store import ObjectStore
from app.models.db import DiagramSpec, Report
from app.models.report_quality import ClaimGraph, FinancialImpactItem, ReportQualityIssue, ReportQualityResult
from app.services.case_service import CaseService
from app.services.evidence_service import DETERMINISTIC_EVIDENCE_TYPES, EvidenceService
from app.services.finding_service import FindingService


class ReportQualityService:
    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def evaluate(self, case_id: str, report_version: int, claim_graph: ClaimGraph, markdown: str | None = None) -> ReportQualityResult:
        case = CaseService(self.db).get_case(case_id)
        transactions = CaseService(self.db).list_transactions(case_id)
        evidence = EvidenceService(self.db).list_for_case(case_id)
        findings = [item for item in FindingService(self.db).list_for_case(case_id) if item.reviewer_status != "rejected"]
        diagrams = list(self.db.scalars(select(DiagramSpec).where(DiagramSpec.case_id == case_id)).all())
        report_type = str(claim_graph.metadata.get("report_type") or "attack_rca")
        blocking: list[ReportQualityIssue] = []
        warnings: list[ReportQualityIssue] = []
        infos: list[ReportQualityIssue] = []

        for finding in findings:
            if finding.severity in {"critical", "high"} and not EvidenceService(self.db).has_deterministic_evidence(finding.evidence_ids):
                blocking.append(
                    self._issue(
                        "blocking",
                        "RQ-BLOCK-001",
                        f"High/Critical finding lacks deterministic evidence: {finding.title}",
                        evidence_ids=list(finding.evidence_ids),
                        recommendation="Bind at least one deterministic evidence row before publishing.",
                    )
                )

        if report_type == "attack_rca" and not transactions:
            blocking.append(self._issue("blocking", "RQ-BLOCK-002", "Full attack RCA has no transaction scope.", recommendation="Downgrade to a boundary report or collect transaction scope."))

        for claim in claim_graph.claims:
            if claim.claim_type == "root_cause" and not claim.support_evidence_ids:
                blocking.append(self._issue("blocking", "RQ-BLOCK-003", "Root-cause claim has no supporting evidence.", section=claim.section, claim_id=claim.claim_id))

        for item in claim_graph.financial_impact:
            if item.category == "confirmed_loss" and item.usd_value and (not item.price_source or not item.support_evidence_ids):
                blocking.append(
                    self._issue(
                        "blocking",
                        "RQ-BLOCK-004",
                        "Confirmed USD loss lacks price source or supporting evidence.",
                        evidence_ids=list(item.support_evidence_ids),
                        recommendation="Downgrade to probable_loss/unpriced_movement or attach price evidence.",
                    )
                )

        if self._is_simple_native_transfer(case, evidence, findings) and report_type != "transaction_preanalysis":
            blocking.append(self._issue("blocking", "RQ-BLOCK-005", "Plain native transfer was not downgraded to transaction pre-analysis."))

        if case.seed_type == "address" and (not transactions or any(item.claim_key == "address_discovery_explorer_missing" for item in evidence)):
            has_attack_claim = any(claim.claim_type in {"root_cause", "loss"} for claim in claim_graph.claims) or report_type == "attack_rca"
            if has_attack_claim:
                blocking.append(self._issue("blocking", "RQ-BLOCK-006", "Address seed without transaction scope produced attack RCA claims."))

        for tx in transactions:
            if not tx.phase or tx.phase == "unknown":
                warnings.append(self._issue("warning", "RQ-WARN-001", f"Timeline transaction has missing/unknown phase: {tx.tx_hash}"))

        for diagram in diagrams:
            for edge in ((diagram.nodes_edges_json or {}).get("edges") or []):
                if isinstance(edge, dict) and not edge.get("evidence_ids") and not edge.get("evidence_id"):
                    warnings.append(self._issue("warning", "RQ-WARN-002", f"Diagram edge has no evidence id: {diagram.diagram_type}", section="数据流图"))
                    break

        for row in evidence:
            decoded = row.decoded or {}
            if row.claim_key != "fund_flow_edges":
                continue
            for edge in decoded.get("fund_flow_edges") or []:
                if not isinstance(edge, dict):
                    continue
                if not edge.get("amount") or not edge.get("asset") or not edge.get("confidence"):
                    warnings.append(self._issue("warning", "RQ-WARN-003", "Fund-flow edge lacks amount, asset, or confidence.", evidence_ids=[row.id]))
                    break

        if report_type == "attack_rca" and not claim_graph.alternative_hypotheses:
            warnings.append(self._issue("warning", "RQ-WARN-004", "Full attack RCA has no alternative hypothesis table.", section="根因分析"))

        if report_type == "attack_rca" and not self._has_reproduction_steps(claim_graph, markdown):
            warnings.append(self._issue("warning", "RQ-WARN-005", "Full attack RCA lacks reproduction / verification steps."))

        if any(claim.claim_type == "remediation" for claim in claim_graph.claims) and not any(claim.claim_type == "root_cause" for claim in claim_graph.claims):
            warnings.append(self._issue("warning", "RQ-WARN-006", "Remediation claim has no corresponding root-cause claim."))

        score = max(0, 100 - 30 * len(blocking) - 5 * len(warnings))
        return ReportQualityResult(
            case_id=case_id,
            report_version=report_version,
            score=score,
            blocking_issues=blocking,
            warnings=warnings,
            infos=infos,
            metadata={"report_type": report_type, "rules_version": "v1", "markdown_checked": markdown is not None},
        )

    def assert_publishable(self, report: Report) -> None:
        quality_path = (report.metadata_json or {}).get("quality_result_path")
        if not quality_path:
            raise HTTPException(status_code=422, detail={"message": "Report quality metadata missing; regenerate report before publish.", "rule_id": "RQ-BLOCK-MISSING-QUALITY"})
        try:
            quality = ReportQualityResult.model_validate(json.loads(self.object_store.get_bytes(quality_path).decode("utf-8")))
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"message": f"Report quality result unavailable: {exc}", "rule_id": "RQ-BLOCK-MISSING-QUALITY"}) from exc
        if quality.blocking_issues:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Report has blocking quality issues",
                    "blocking_issue_count": len(quality.blocking_issues),
                    "issues": [issue.model_dump() for issue in quality.blocking_issues[:10]],
                },
            )

    def load_claim_graph(self, report: Report) -> ClaimGraph:
        path = (report.metadata_json or {}).get("claim_graph_path")
        if not path:
            raise HTTPException(status_code=404, detail="Report claim graph not found; regenerate report")
        return ClaimGraph.model_validate(json.loads(self.object_store.get_bytes(path).decode("utf-8")))

    def load_quality_result(self, report: Report) -> ReportQualityResult:
        path = (report.metadata_json or {}).get("quality_result_path")
        if not path:
            raise HTTPException(status_code=404, detail="Report quality result not found; regenerate report")
        return ReportQualityResult.model_validate(json.loads(self.object_store.get_bytes(path).decode("utf-8")))

    def _issue(
        self,
        severity: str,
        rule_id: str,
        message: str,
        section: str | None = None,
        claim_id: str | None = None,
        evidence_ids: list[str] | None = None,
        recommendation: str | None = None,
    ) -> ReportQualityIssue:
        return ReportQualityIssue(
            issue_id=f"{rule_id}-{abs(hash((rule_id, message, claim_id))) % 1_000_000:06d}",
            severity=severity,  # type: ignore[arg-type]
            rule_id=rule_id,
            message=message,
            section=section,
            claim_id=claim_id,
            evidence_ids=evidence_ids or [],
            recommendation=recommendation,
        )

    def _is_simple_native_transfer(self, case, evidence: list, findings: list) -> bool:
        if case.seed_type != "transaction":
            return False
        if case.attack_type or any(item.severity in {"medium", "high", "critical"} for item in findings):
            return False
        has_native = any(item.claim_key == "native_value_transfer" for item in evidence)
        if not has_native:
            return False
        disqualifying = {"trace_call", "source_line", "signature", "state_call"}
        if any(item.source_type in disqualifying for item in evidence):
            return False
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "evm_receipt_events_normalized" and int(decoded.get("log_count") or 0) > 0:
                return False
            if item.claim_key == "transaction_in_case_scope" and (decoded.get("metadata") or {}).get("input") not in {None, "", "0x"}:
                return False
        return True

    def _has_reproduction_steps(self, claim_graph: ClaimGraph, markdown: str | None) -> bool:
        if markdown and ("复现" in markdown or "验证步骤" in markdown or "reproduction" in markdown.lower()):
            return True
        return any("复现" in claim.section or "验证" in claim.section or claim.metadata.get("reproduction_step") for claim in claim_graph.claims)

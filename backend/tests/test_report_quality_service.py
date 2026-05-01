from __future__ import annotations

from app.models.db import DiagramSpec
from app.models.report_quality import ClaimGraph, FinancialImpactItem, ReportClaim
from app.models.schemas import FindingCreate, TransactionCreate
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService
from app.services.report_quality_service import ReportQualityService


def _case(client, **overrides):
    payload = {
        "network_key": "megaeth",
        "seed_type": "transaction",
        "seed_value": "0x" + "7" * 64,
        "depth": "full",
    }
    payload.update(overrides)
    return client.post("/api/cases", json=payload).json()


def _add_tx(db_session, case_id: str, phase: str = "seed"):
    return CaseService(db_session).add_transaction(case_id, TransactionCreate(tx_hash="0x" + "8" * 64, phase=phase, metadata={}))


def _graph(case_id: str, *, claims=None, financial=None, alternatives=None, report_type: str = "attack_rca") -> ClaimGraph:
    return ClaimGraph(
        case_id=case_id,
        report_version=1,
        renderer_family="generic_fallback",
        claims=claims or [],
        financial_impact=financial or [],
        alternative_hypotheses=alternatives or [],
        metadata={"report_type": report_type},
    )


def _rule_ids(result):
    return {issue.rule_id for issue in result.blocking_issues + result.warnings + result.infos}


def test_quality_blocks_high_finding_without_deterministic_evidence(client, db_session):
    case = _case(client)
    _add_tx(db_session, case["id"])
    evidence = EvidenceService(db_session).create_evidence(case["id"], "artifact_summary", "test", "weak_artifact", None, {}, "medium")
    FindingService(db_session).create_finding(
        case["id"],
        FindingCreate(
            title="Weak high finding",
            finding_type="root_cause",
            severity="high",
            confidence="medium",
            claim="This high finding is intentionally backed by weak evidence.",
            evidence_ids=[evidence.id],
            created_by="test",
        ),
    )

    result = ReportQualityService(db_session).evaluate(case["id"], 1, _graph(case["id"]))

    assert "RQ-BLOCK-001" in _rule_ids(result)
    assert result.score <= 70


def test_quality_blocks_root_cause_without_evidence_and_unpriced_confirmed_loss(client, db_session):
    case = _case(client, seed_value="0x" + "9" * 64)
    _add_tx(db_session, case["id"])
    graph = _graph(
        case["id"],
        claims=[
            ReportClaim(
                claim_id="C-ROOT-001",
                section="根因分析",
                claim_type="root_cause",
                text="Root cause without support.",
                confidence="medium",
            )
        ],
        financial=[
            FinancialImpactItem(
                item_id="FI-001",
                category="confirmed_loss",
                asset="USD",
                usd_value="1000.00",
                confidence="medium",
            )
        ],
    )

    result = ReportQualityService(db_session).evaluate(case["id"], 1, graph)

    assert {"RQ-BLOCK-003", "RQ-BLOCK-004"} <= _rule_ids(result)


def test_quality_blocks_plain_native_transfer_written_as_attack(client, db_session):
    tx_hash = "0x" + "a" * 64
    case = _case(client, seed_value=tx_hash)
    tx = _add_tx(db_session, case["id"])
    EvidenceService(db_session).create_evidence(case["id"], "balance_diff", "test", "native_value_transfer", None, {"amount_raw": "1"}, "high", tx.id)

    result = ReportQualityService(db_session).evaluate(case["id"], 1, _graph(case["id"], report_type="attack_rca"))

    assert "RQ-BLOCK-005" in _rule_ids(result)


def test_quality_blocks_address_seed_without_scope_written_as_attack(client, db_session):
    case = _case(client, seed_type="address", seed_value="0x" + "b" * 40)
    graph = _graph(
        case["id"],
        claims=[
            ReportClaim(
                claim_id="C-ROOT-001",
                section="根因分析",
                claim_type="root_cause",
                text="Unsupported attack path from an address seed.",
                confidence="low",
            )
        ],
        report_type="attack_rca",
    )

    result = ReportQualityService(db_session).evaluate(case["id"], 1, graph)

    assert "RQ-BLOCK-006" in _rule_ids(result)


def test_quality_warning_rules_cover_timeline_diagrams_fund_flow_and_remediation(client, db_session):
    case = _case(client, seed_value="0x" + "c" * 64)
    _add_tx(db_session, case["id"], phase="unknown")
    EvidenceService(db_session).create_evidence(
        case["id"],
        "receipt_log",
        "test",
        "fund_flow_edges",
        None,
        {"fund_flow_edges": [{"asset": "USDC", "confidence": "high"}]},
        "high",
    )
    db_session.add(
        DiagramSpec(
            case_id=case["id"],
            diagram_type="attack_flow",
            title="Attack flow",
            mermaid_source="flowchart LR\nA-->B",
            nodes_edges_json={"edges": [{"id": "e1", "source": "A", "target": "B"}]},
            evidence_ids=[],
            confidence="partial",
        )
    )
    db_session.commit()
    graph = _graph(
        case["id"],
        claims=[
            ReportClaim(
                claim_id="C-REMEDIATION-001",
                section="修复建议",
                claim_type="remediation",
                text="Patch the unchecked path.",
                confidence="medium",
            )
        ],
        alternatives=[],
        report_type="attack_rca",
    )

    result = ReportQualityService(db_session).evaluate(case["id"], 1, graph, markdown="No verification appendix")

    assert {"RQ-WARN-001", "RQ-WARN-002", "RQ-WARN-003", "RQ-WARN-004", "RQ-WARN-005", "RQ-WARN-006"} <= _rule_ids(result)

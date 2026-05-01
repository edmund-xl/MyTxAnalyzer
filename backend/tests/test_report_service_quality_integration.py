from __future__ import annotations

import json

from app.core.object_store import ObjectStore
from app.models.schemas import FindingCreate, TransactionCreate
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService


def test_report_generation_writes_claim_and_quality_artifacts_and_publish_gate_blocks(client, db_session):
    tx_hash = "0x" + "d" * 64
    case = client.post(
        "/api/cases",
        json={
            "network_key": "megaeth",
            "seed_type": "transaction",
            "seed_value": tx_hash,
            "depth": "full",
        },
    ).json()
    CaseService(db_session).add_transaction(case["id"], TransactionCreate(tx_hash=tx_hash, phase="exploit", metadata={}))
    evidence = EvidenceService(db_session).create_evidence(
        case["id"],
        "artifact_summary",
        "test",
        "non_deterministic_summary",
        None,
        {"summary": "weak evidence"},
        "medium",
    )
    finding = FindingService(db_session).create_finding(
        case["id"],
        FindingCreate(
            title="High finding without deterministic evidence",
            finding_type="root_cause",
            severity="high",
            confidence="medium",
            claim="The report must not be publishable until deterministic evidence exists.",
            evidence_ids=[evidence.id],
            created_by="test",
        ),
    )
    client.patch(f"/api/findings/{finding.id}/review", json={"reviewer_status": "approved"})

    created = client.post(f"/api/cases/{case['id']}/reports", json={"format": "markdown"})
    assert created.status_code == 201, created.text
    report = created.json()
    metadata = report["metadata"]
    assert metadata["claim_graph_path"].endswith(".claims.json")
    assert metadata["quality_result_path"].endswith(".quality.json")
    assert metadata["blocking_issue_count"] >= 1
    assert metadata["claim_count"] >= 1

    store = ObjectStore()
    claims = json.loads(store.get_bytes(metadata["claim_graph_path"]).decode("utf-8"))
    quality = json.loads(store.get_bytes(metadata["quality_result_path"]).decode("utf-8"))
    assert claims["case_id"] == case["id"]
    assert any(issue["rule_id"] == "RQ-BLOCK-001" for issue in quality["blocking_issues"])

    claims_response = client.get(f"/api/reports/{report['id']}/claims", headers={"x-user-role": "reader"})
    quality_response = client.get(f"/api/reports/{report['id']}/quality", headers={"x-user-role": "reader"})
    assert claims_response.status_code == 200, claims_response.text
    assert quality_response.status_code == 200, quality_response.text
    assert claims_response.json()["case_id"] == case["id"]
    assert quality_response.json()["score"] == metadata["quality_score"]

    publish = client.post(f"/api/reports/{report['id']}/publish")
    assert publish.status_code == 422
    assert "Report has blocking quality issues" in publish.text

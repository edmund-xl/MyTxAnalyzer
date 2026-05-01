from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import FindingCreate, TransactionCreate
from app.services.case_service import CaseService
from app.services.claim_builder_service import ClaimBuilderService
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService


def _case(client, **overrides):
    payload = {
        "network_key": "megaeth",
        "seed_type": "transaction",
        "seed_value": "0x" + "1" * 64,
        "depth": "full",
    }
    payload.update(overrides)
    return client.post("/api/cases", json=payload).json()


def test_claim_builder_creates_address_boundary_without_attack_claims(client, db_session):
    case = _case(client, seed_type="address", seed_value="0x" + "2" * 40)

    graph = ClaimBuilderService(db_session).build_for_report(case["id"], 1, "generic_fallback")

    assert graph.metadata["report_type"] == "address_boundary"
    assert graph.claims[0].claim_type == "boundary"
    assert graph.alternative_hypotheses == []
    assert all(claim.claim_type not in {"root_cause", "loss"} for claim in graph.claims)


def test_claim_builder_creates_native_transfer_preanalysis_claims(client, db_session):
    tx_hash = "0x" + "3" * 64
    case = _case(client, seed_value=tx_hash)
    tx = CaseService(db_session).add_transaction(case["id"], TransactionCreate(tx_hash=tx_hash, phase="seed", metadata={"input": "0x"}))
    tx.block_number = 123
    tx.block_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db_session.add(tx)
    db_session.commit()
    evidence_service = EvidenceService(db_session)
    evidence_service.create_evidence(case["id"], "tx_metadata", "test", "transaction_in_case_scope", None, {"tx_hash": tx_hash}, "high", tx.id)
    evidence_service.create_evidence(
        case["id"],
        "balance_diff",
        "test",
        "native_value_transfer",
        None,
        {"from": "0x" + "4" * 40, "to": "0x" + "5" * 40, "asset": "MEGAETH", "amount_raw": "1000"},
        "high",
        tx.id,
    )

    graph = ClaimBuilderService(db_session).build_for_report(case["id"], 1, "generic_fallback")

    assert graph.metadata["report_type"] == "transaction_preanalysis"
    assert {claim.claim_type for claim in graph.claims} >= {"fact", "boundary"}
    assert graph.financial_impact[0].category == "unpriced_movement"


def test_claim_builder_creates_attack_claims_alternatives_and_financial_layers(client, db_session):
    tx_hash = "0x" + "6" * 64
    case = _case(client, title="Renderer quality attack case", seed_value=tx_hash)
    db_case = CaseService(db_session).get_case(case["id"])
    db_case.attack_type = "cross_contract_reentrancy"
    db_case.root_cause_one_liner = "Cross-contract reentrancy bypassed the old guard."
    db_case.loss_usd = 1000
    db_case.severity = "high"
    db_session.add(db_case)
    db_session.commit()
    tx = CaseService(db_session).add_transaction(case["id"], TransactionCreate(tx_hash=tx_hash, phase="exploit", metadata={}))
    evidence = EvidenceService(db_session).create_evidence(case["id"], "receipt_log", "test", "reentrancy_signal", None, {"event": "Borrow"}, "high", tx.id)
    FindingService(db_session).create_finding(
        case["id"],
        FindingCreate(
            title="Reentrancy guard bypass",
            finding_type="root_cause",
            severity="high",
            confidence="high",
            claim="The exploit re-entered through a cross-contract path.",
            evidence_ids=[evidence.id],
            created_by="test",
        ),
    )

    graph = ClaimBuilderService(db_session).build_for_report(case["id"], 1, "cross_contract_reentrancy")

    assert graph.metadata["report_type"] == "attack_rca"
    assert any(claim.claim_type == "root_cause" for claim in graph.claims)
    assert graph.alternative_hypotheses
    assert any(item.category == "probable_loss" for item in graph.financial_impact)

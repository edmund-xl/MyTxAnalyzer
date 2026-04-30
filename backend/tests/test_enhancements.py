from __future__ import annotations

import sys
from pathlib import Path

from app.core.public_rpc import resolve_explorer_api_key
from app.models.db import Network
from app.services.case_service import CaseService
from app.services.evidence_parser_service import EvidenceParserService
from app.services.evidence_service import EvidenceService
from app.services.report_renderer_registry import ReportRendererRegistry
from app.services.workflow_run_service import WorkflowRunService
from app.workers.fund_flow_worker import FundFlowWorker
from app.workers.rca_agent_worker import RCAAgentWorker
from app.workers.tx_discovery_worker import TxDiscoveryWorker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from seed_performance_data import seed_performance_data  # noqa: E402


def test_provider_explorer_key_resolution_prefers_network_specific_env(db_session, monkeypatch):
    network = db_session.get(Network, "eth")
    assert network is not None
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    monkeypatch.setenv("ETH_EXPLORER_API_KEY", "eth-specific")

    key, source = resolve_explorer_api_key(network)

    assert key == "eth-specific"
    assert source == "env:ETH_EXPLORER_API_KEY"


def test_evm_receipt_parser_normalizes_transfer_and_approval():
    tx_hash = "0x" + "1" * 64
    owner = "0x" + "a" * 40
    receiver = "0x" + "b" * 40
    spender = "0x" + "c" * 40
    token = "0x" + "d" * 40
    receipt = {
        "status": "0x1",
        "blockNumber": "0x10",
        "logs": [
            {
                "address": token,
                "logIndex": "0x0",
                "topics": [
                    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                    "0x" + "0" * 24 + owner[2:],
                    "0x" + "0" * 24 + receiver[2:],
                ],
                "data": "0x" + f"{1234:064x}",
            },
            {
                "address": token,
                "logIndex": "0x1",
                "topics": [
                    "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925",
                    "0x" + "0" * 24 + owner[2:],
                    "0x" + "0" * 24 + spender[2:],
                ],
                "data": "0x" + f"{999:064x}",
            },
        ],
    }

    normalized = EvidenceParserService().normalize_evm_receipt(receipt, tx_hash)

    assert normalized["status"] == 1
    assert normalized["transfer_count"] == 1
    assert normalized["approval_count"] == 1
    assert normalized["fund_flow_edges"][0]["from"] == owner
    assert normalized["fund_flow_edges"][0]["to"] == receiver
    assert normalized["fund_flow_edges"][0]["amount_raw"] == "1234"


def test_fund_flow_worker_consumes_standardized_transfer_evidence(client, db_session):
    case = client.post(
        "/api/cases",
        json={
            "network_key": "eth",
            "seed_type": "transaction",
            "seed_value": "0x" + "e" * 64,
            "depth": "full",
        },
    ).json()
    EvidenceService(db_session).create_evidence(
        case_id=case["id"],
        source_type="receipt_log",
        producer="test",
        claim_key="evm_receipt_events_normalized",
        raw_path="file://receipt.json",
        decoded={
            "fund_flow_edges": [
                {
                    "from": "0x" + "1" * 40,
                    "to": "0x" + "2" * 40,
                    "asset": "USDC",
                    "amount": "1000000",
                    "confidence": "high",
                    "tx_hash": "0x" + "e" * 64,
                }
            ]
        },
        confidence="high",
    )

    result = FundFlowWorker(db_session).run(case["id"])

    assert result.status == "success"
    rows = client.get(f"/api/cases/{case['id']}/evidence").json()
    flow = next(item for item in rows if item["claim_key"] == "fund_flow_edges")
    assert flow["decoded"]["edge_count"] == 1
    assert flow["decoded"]["fund_flow_edges"][0]["asset"] == "USDC"


def test_report_renderer_registry_classifies_common_attack_types(client, db_session):
    case = client.post(
        "/api/cases",
        json={
            "title": "GMX V1 cross-contract reentrancy",
            "network_key": "arbitrum",
            "seed_type": "transaction",
            "seed_value": "0x" + "f" * 64,
            "depth": "full",
        },
    ).json()
    db_case = CaseService(db_session).get_case(case["id"])
    db_case.attack_type = "cross_contract_reentrancy"
    db_session.add(db_case)
    db_session.commit()

    renderer = ReportRendererRegistry().select(db_case, [], [])

    assert renderer == "cross_contract_reentrancy"


def test_workflow_run_api_lists_and_cancels(client, db_session):
    case = client.post(
        "/api/cases",
        json={
            "network_key": "megaeth",
            "seed_type": "transaction",
            "seed_value": "0x" + "9" * 64,
            "depth": "full",
        },
    ).json()
    workflow = WorkflowRunService(db_session).start(case["id"], "test-workflow-1", "inline", {"test": True})

    listed = client.get(f"/api/cases/{case['id']}/workflow-runs")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["id"] == workflow.id

    cancelled = client.post(f"/api/cases/workflow-runs/{workflow.id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"


def test_performance_seed_smoke(db_session):
    result = seed_performance_data(db_session, case_count=3, evidence_count=7, job_count=5, report_count=3, diagram_count=9, export_count=2, reset=True)

    assert result == {"cases": 3, "evidence": 7, "jobs": 5, "reports": 3, "diagrams": 9, "exports": 2}


def test_address_seed_report_is_boundary_not_attack_rca(client, db_session, monkeypatch):
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    monkeypatch.delenv("ETH_EXPLORER_API_KEY", raising=False)
    case = client.post(
        "/api/cases",
        json={
            "network_key": "eth",
            "seed_type": "address",
            "seed_value": "0x" + "1" * 40,
            "depth": "full",
        },
    ).json()

    discovery = TxDiscoveryWorker(db_session).run(case["id"])
    rca = RCAAgentWorker(db_session).run(case["id"])
    report = client.post(f"/api/cases/{case['id']}/reports", json={"format": "markdown"})
    content = client.get(f"/api/cases/{case['id']}/reports/{report.json()['id']}").json()["content"]

    assert discovery.status == "partial"
    assert rca.status == "success"
    assert "地址线索预分析报告" in content
    assert "不是完整攻击 RCA" in content
    assert "不能确认攻击路径、根因或损失" in content
    assert "铸造虚假抵押品" not in content


def test_address_seed_rejects_evm_transaction_hash(client):
    response = client.post(
        "/api/cases",
        json={
            "network_key": "megaeth",
            "seed_type": "address",
            "seed_value": "0x" + "a" * 64,
            "depth": "full",
        },
    )

    assert response.status_code == 422
    assert "use seed_type=transaction" in response.text


def test_address_seed_accepts_evm_address(client):
    response = client.post(
        "/api/cases",
        json={
            "network_key": "megaeth",
            "seed_type": "address",
            "seed_value": "0x" + "a" * 40,
            "depth": "full",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["seed_type"] == "address"

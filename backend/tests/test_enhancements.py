from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

from app.core.public_rpc import resolve_explorer_api_key
from app.models.db import Network
from app.models.schemas import TransactionCreate
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


def test_alert_seed_report_is_external_event_preanalysis_not_attack_rca(client, db_session):
    case = client.post(
        "/api/cases",
        json={
            "title": "DefiLlama latest Wasabi Perps",
            "network_key": "eth",
            "seed_type": "alert",
            "seed_value": "https://defillama.com/hacks?name=Wasabi%20Perps",
            "depth": "full",
        },
    ).json()
    EvidenceService(db_session).create_evidence(
        case_id=case["id"],
        source_type="external_alert",
        producer="test",
        claim_key="defillama_hack_record",
        raw_path="https://api.llama.fi/hacks",
        decoded={
            "name": "Wasabi Perps",
            "date": "2026-04-30",
            "chains": ["Ethereum", "Base", "Berachain", "Blast"],
            "amount": 5500000,
            "classification": "Protocol Logic",
            "technique": "Admin Key Compromised",
        },
        confidence="partial",
    )

    rca = RCAAgentWorker(db_session).run(case["id"])
    report = client.post(f"/api/cases/{case['id']}/reports", json={"format": "markdown"})
    report_id = report.json()["id"]
    detail = client.get(f"/api/cases/{case['id']}/reports/{report_id}")
    quality = client.get(f"/api/reports/{report_id}/quality")
    content = detail.json()["content"]

    assert rca.status == "success"
    assert "外部事件预分析报告" in content
    assert "不是完整攻击 RCA" in content
    assert "Admin Key Compromised" in content
    assert "攻击事件 RCA 报告" not in content
    assert not any(issue["rule_id"] == "RQ-BLOCK-002" for issue in quality.json()["blocking_issues"])
    assert not any(issue["rule_id"] == "RQ-WARN-002" for issue in quality.json()["warnings"])


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


def test_transaction_seed_hydrates_from_full_block_fallback(client, db_session, monkeypatch):
    tx_hash = "0x" + "b" * 64

    class FakeEth:
        def get_transaction(self, _tx_hash):
            raise RuntimeError("eth_getTransactionByHash unavailable")

        def get_transaction_receipt(self, _tx_hash):
            return {
                "transactionHash": tx_hash,
                "status": "0x1",
                "blockNumber": "0x8e6f12",
                "transactionIndex": "0x3",
                "gasUsed": "0xea60",
                "logs": [],
            }

        def get_block(self, _block_number, full_transactions=False):
            assert full_transactions is True
            return {
                "timestamp": "0x69a094e5",
                "transactions": [
                    {
                        "hash": bytes.fromhex(tx_hash[2:]),
                        "from": "0xb2b34b33f96952a0e17540250481f3b99fda854b",
                        "to": "0xc37ae078cf9961ce22765e3de4a297a61ba1877f",
                        "nonce": "0x8",
                        "value": "0x2386f26fc10000",
                        "input": "0x",
                        "gas": "0x15f90",
                        "gasPrice": "0x155cc0",
                    }
                ],
            }

    class FakeWeb3:
        eth = FakeEth()

    monkeypatch.setattr("app.workers.tx_discovery_worker.resolve_rpc_url", lambda network: ("http://rpc.local", "test"))
    monkeypatch.setattr("app.workers.tx_discovery_worker.apply_network_middlewares", lambda _w3, _network_key: FakeWeb3())
    case = client.post(
        "/api/cases",
        json={
            "network_key": "megaeth",
            "seed_type": "transaction",
            "seed_value": tx_hash,
            "depth": "full",
        },
    ).json()

    result = TxDiscoveryWorker(db_session).run(case["id"])
    rows = client.get(f"/api/cases/{case['id']}/transactions").json()

    assert result.status == "success"
    assert rows[0]["block_number"] == 9334546
    assert rows[0]["from_address"] == "0xb2b34b33f96952a0e17540250481f3b99fda854b"
    assert rows[0]["to_address"] == "0xc37ae078cf9961ce22765e3de4a297a61ba1877f"
    assert rows[0]["metadata"]["transaction_source"] == "eth_getBlockByNumber_full_transactions"


def test_simple_native_transfer_report_is_not_attack_template(client, db_session):
    tx_hash = "0x" + "c" * 64
    case = client.post(
        "/api/cases",
        json={
            "network_key": "megaeth",
            "seed_type": "transaction",
            "seed_value": tx_hash,
            "depth": "full",
        },
    ).json()
    tx = CaseService(db_session).add_transaction(case["id"], TransactionCreate(tx_hash=tx_hash, phase="seed", metadata={"source": "test"}))
    tx.block_number = 9334546
    tx.block_timestamp = datetime(2026, 2, 26, 18, 45, 57, tzinfo=timezone.utc)
    tx.tx_index = 3
    tx.from_address = "0xb2b34b33f96952a0e17540250481f3b99fda854b"
    tx.to_address = "0xc37ae078cf9961ce22765e3de4a297a61ba1877f"
    tx.value_wei = 10_000_000_000_000_000
    tx.status = 1
    tx.metadata_json = {"input": "0x", "log_count": 0, "transaction_source": "test"}
    db_session.add(tx)
    db_session.commit()
    EvidenceService(db_session).create_evidence(
        case_id=case["id"],
        tx_id=tx.id,
        source_type="tx_metadata",
        producer="test",
        claim_key="transaction_in_case_scope",
        raw_path=None,
        decoded={
            "tx_hash": tx_hash,
            "block_number": tx.block_number,
            "timestamp": tx.block_timestamp.isoformat(),
            "from": tx.from_address,
            "to": tx.to_address,
            "value_wei": str(tx.value_wei),
            "status": tx.status,
            "metadata": tx.metadata_json,
        },
        confidence="high",
    )

    FundFlowWorker(db_session).run(case["id"])
    RCAAgentWorker(db_session).run(case["id"])
    updated = client.get(f"/api/cases/{case['id']}").json()
    report = client.post(f"/api/cases/{case['id']}/reports", json={"format": "markdown"})
    content = client.get(f"/api/cases/{case['id']}/reports/{report.json()['id']}").json()["content"]

    assert updated["severity"] == "info"
    assert updated["attack_type"] is None
    assert "链上交易预分析报告" in content
    assert "不是攻击 RCA" in content
    assert "攻击者 / 接收地址" not in content
    assert "攻击流程图" not in content
    assert "铸造虚假抵押品" not in content

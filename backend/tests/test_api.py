from __future__ import annotations

import time

from app.models.schemas import FindingCreate
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService
from app.workers.tx_discovery_worker import TxDiscoveryWorker


def test_health_networks_and_case_crud(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    txanalyzer_health = client.get("/api/health/txanalyzer")
    assert txanalyzer_health.status_code == 200
    assert {"ready", "root_exists", "script_exists", "required_packages"} <= txanalyzer_health.json().keys()

    networks = client.get("/api/networks")
    assert networks.status_code == 200
    assert {item["key"] for item in networks.json()} >= {"eth", "bsc", "megaeth"}

    created = client.post(
        "/api/cases",
        json={
            "title": "MegaETH Golden Case",
            "network_key": "megaeth",
            "seed_type": "transaction",
            "seed_value": "0x" + "a" * 64,
            "time_window_hours": 8,
            "depth": "full",
            "language": "zh-CN",
        },
    )
    assert created.status_code == 201, created.text
    case = created.json()
    assert case["status"] == "CREATED"

    listed = client.get("/api/cases")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == case["id"]

    summary = client.get("/api/cases/summary")
    assert summary.status_code == 200
    assert summary.json()["total_cases"] >= 1

    paged = client.get("/api/cases?limit=1&offset=0")
    assert paged.status_code == 200
    assert len(paged.json()) == 1

    fetched = client.get(f"/api/cases/{case['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["seed_value"].startswith("0x")

    detail_summary = client.get(f"/api/cases/{case['id']}/summary")
    assert detail_summary.status_code == 200
    assert detail_summary.json() == {
        "transaction_count": 0,
        "evidence_count": 0,
        "finding_count": 0,
        "report_count": 0,
        "diagram_count": 0,
        "job_count": 0,
    }


def test_finding_review_and_report_generation(client, db_session):
    case = client.post(
        "/api/cases",
        json={
            "network_key": "megaeth",
            "seed_type": "transaction",
            "seed_value": "0x" + "b" * 64,
            "depth": "full",
        },
    ).json()
    evidence = EvidenceService(db_session).create_evidence(
        case_id=case["id"],
        source_type="receipt_log",
        producer="test",
        claim_key="role_granted",
        raw_path="file://test/log.json",
        decoded={"event": "RoleGranted"},
        confidence="high",
    )
    finding = FindingService(db_session).create_finding(
        case["id"],
        FindingCreate(
            title="Role granted",
            finding_type="access_control",
            severity="high",
            confidence="high",
            claim="A role grant was observed.",
            evidence_ids=[evidence.id],
            created_by="test",
        ),
    )

    review = client.patch(f"/api/findings/{finding.id}/review", json={"reviewer_status": "approved"})
    assert review.status_code == 200, review.text
    assert review.json()["reviewer_status"] == "approved"

    report = client.post(f"/api/cases/{case['id']}/reports", json={"format": "markdown"})
    assert report.status_code == 201, report.text
    report_id = report.json()["id"]
    detail = client.get(f"/api/cases/{case['id']}/reports/{report_id}")
    assert detail.status_code == 200
    assert "Role granted" in detail.json()["content"]
    assert "```mermaid" in detail.json()["content"]

    diagrams = client.get(f"/api/cases/{case['id']}/diagrams")
    assert diagrams.status_code == 200
    assert {item["diagram_type"] for item in diagrams.json()} == {"attack_flow", "fund_flow", "evidence_map"}

    export = client.post(f"/api/reports/{report_id}/exports", json={"format": "pdf"})
    assert export.status_code == 201, export.text
    export_body = export.json()
    assert export_body["format"] == "pdf"
    assert export_body["status"] in {"running", "success"}

    current_export = export_body
    for _ in range(20):
        exports = client.get(f"/api/reports/{report_id}/exports")
        assert exports.status_code == 200, exports.text
        current_export = next(item for item in exports.json() if item["id"] == export_body["id"])
        if current_export["status"] == "success":
            break
        time.sleep(0.1)
    assert current_export["status"] == "success", current_export

    download = client.get(f"/api/report-exports/{current_export['id']}/download")
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")


def test_alert_seed_discovery_does_not_create_fake_transaction(client, db_session):
    case = client.post(
        "/api/cases",
        json={
            "title": "DefiLlama Purrlend alert",
            "network_key": "megaeth",
            "seed_type": "alert",
            "seed_value": "https://x.com/kirbyongeo/status/2047955753374552511",
            "depth": "quick",
        },
    ).json()

    result = TxDiscoveryWorker(db_session).run(case["id"])

    assert result.status == "success"
    assert client.get(f"/api/cases/{case['id']}/transactions").json() == []
    evidence = client.get(f"/api/cases/{case['id']}/evidence").json()
    assert any(item["claim_key"] == "external_incident_seed" for item in evidence)


def test_sui_scallop_case_uses_native_rpc_artifacts(client, db_session, monkeypatch):
    digest = "6WNDjCX3W852hipq6yrHhpUaSFHSPWfTxuLKaQkgNfVL"

    def fake_sui_rpc_call(self, rpc_url, method, params):
        assert method == "sui_getTransactionBlock"
        return {
            "digest": digest,
            "checkpoint": "269215678",
            "timestampMs": "1777203900207",
            "transaction": {
                "data": {
                    "sender": "0x27bc7a3c4f406cfa91551c32490ad7f5029414578c0649ab4ddbd232e76ef44e",
                    "transaction": {
                        "inputs": [],
                        "transactions": [
                            {"MoveCall": {"package": "0xde5c", "module": "mint", "function": "mint", "type_arguments": []}},
                            {"MoveCall": {"package": "0xec1a", "module": "user", "function": "new_spool_account", "type_arguments": []}},
                            {"MoveCall": {"package": "0xec1a", "module": "user", "function": "stake", "type_arguments": []}},
                            {"MoveCall": {"package": "0xec1a", "module": "user", "function": "update_points", "type_arguments": []}},
                            {"MoveCall": {"package": "0xec1a", "module": "user", "function": "redeem_rewards", "type_arguments": []}},
                        ],
                    },
                }
            },
            "effects": {"status": {"status": "success"}},
            "events": [
                {
                    "type": "0xec1a::user::SpoolAccountRedeemRewardsEventV2",
                    "packageId": "0xec1a",
                    "transactionModule": "user",
                    "sender": "0x27bc7a3c4f406cfa91551c32490ad7f5029414578c0649ab4ddbd232e76ef44e",
                    "parsedJson": {
                        "rewards": "150098061595978",
                        "rewards_pool_id": "0x162250ef72393a4ad3d46294c4e1bdfcb03f04c869d390e7efbfc995353a7ee9",
                    },
                }
            ],
            "balanceChanges": [
                {
                    "owner": {"AddressOwner": "0x27bc7a3c4f406cfa91551c32490ad7f5029414578c0649ab4ddbd232e76ef44e"},
                    "coinType": "0x2::sui::SUI",
                    "amount": "150098051263289",
                }
            ],
        }

    monkeypatch.setattr(TxDiscoveryWorker, "_sui_rpc_call", fake_sui_rpc_call)
    case = client.post(
        "/api/cases",
        json={
            "title": "Scallop Lend sSUI reward pool incident",
            "network_key": "sui",
            "seed_type": "transaction",
            "seed_value": digest,
            "depth": "full",
        },
    ).json()

    result = TxDiscoveryWorker(db_session).run(case["id"])

    assert result.status == "success"
    txs = client.get(f"/api/cases/{case['id']}/transactions").json()
    assert txs[0]["tx_hash"] == digest
    evidence = client.get(f"/api/cases/{case['id']}/evidence").json()
    flow = next(item for item in evidence if item["claim_key"] == "sui_reward_redemption_flow")
    incident = EvidenceService(db_session).create_evidence(
        case_id=case["id"],
        source_type="external_incident_report",
        producer="manual_import",
        claim_key="scallop_ssui_reward_pool_incident_summary",
        raw_path="https://www.kucoin.com/news/flash/scallop-loses-150-000-sui-due-to-ssui-reward-pool-vulnerability",
        decoded={
            "project": "Scallop Lend",
            "date": "2026-04-26",
            "chain": "Sui",
            "loss_summary": "约 150,000 SUI",
            "tx_digest": digest,
            "sources": [{"label": "KuCoin/BlockBeats", "url": "https://www.kucoin.com/news/flash/scallop-loses-150-000-sui-due-to-ssui-reward-pool-vulnerability", "role": "loss/scope"}],
        },
        confidence="medium",
    )
    FindingService(db_session).create_finding(
        case["id"],
        FindingCreate(
            title="Deprecated rewards contract allowed abnormal sSUI reward redemption",
            finding_type="scallop_deprecated_reward_contract",
            severity="high",
            confidence="medium",
            claim="The Scallop incident centers on an old Sui rewards/spool path and an abnormal reward redemption.",
            evidence_ids=[flow["id"], incident.id],
            created_by="test",
        ),
    )
    report = client.post(f"/api/cases/{case['id']}/reports", json={"format": "markdown"})
    assert report.status_code == 201, report.text
    content = client.get(f"/api/cases/{case['id']}/reports/{report.json()['id']}").json()["content"]
    assert "Sui JSON-RPC" in content
    assert "TxAnalyzer 是 EVM 工具，本案不适用" in content
    assert "补齐 seed transaction hash" not in content

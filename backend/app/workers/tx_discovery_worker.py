from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session
from web3 import Web3

from app.core.public_rpc import apply_network_middlewares, resolve_explorer_api_key, resolve_rpc_url
from app.core.object_store import ObjectStore
from app.models.db import Transaction
from app.models.schemas import TransactionCreate, WorkerResult
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.evidence_parser_service import EvidenceParserService
from app.services.job_service import JobService


class TxDiscoveryWorker:
    name = "tx_discovery_worker"

    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def run(self, case_id: str) -> WorkerResult:
        case_service = CaseService(self.db)
        case = case_service.get_case(case_id)
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {"seed_type": case.seed_type, "seed_value": case.seed_value})
        artifacts: list[str] = []
        evidence_ids: list[str] = []
        try:
            txs: list[Transaction] = []
            extra_evidence_ids: list[str] = []
            if case.seed_type == "transaction":
                txs.append(case_service.add_transaction(case_id, TransactionCreate(tx_hash=case.seed_value, phase="seed", metadata={"source": "seed_transaction"})))
                if getattr(case.network, "network_type", "evm") == "sui":
                    extra_evidence_ids.extend(self._hydrate_sui_transaction(case, txs[0]))
                else:
                    self._hydrate_seed_transaction(case, txs[0])
            elif case.seed_type == "address":
                txs.extend(self._discover_address_txs(case))
            elif case.seed_type == "alert":
                txs = []
            else:
                txs.append(case_service.add_transaction(case_id, TransactionCreate(tx_hash=case.seed_value, phase="seed", metadata={"source": f"seed_{case.seed_type}"})))

            discovery = {
                "seed_type": case.seed_type,
                "seed_value": case.seed_value,
                "alert": self._alert_summary(case) if case.seed_type == "alert" else None,
                "transactions": [self._tx_summary(tx) for tx in txs],
                "transaction_count": len(txs),
            }
            content = json.dumps(discovery, indent=2, sort_keys=True, default=str).encode("utf-8")
            artifact_uri = self.object_store.put_bytes(content, f"cases/{case_id}/discovery/transactions.json", "application/json")
            artifacts.append(artifact_uri)
            EvidenceService(self.db).create_artifact(
                case_id,
                producer=self.name,
                artifact_type="transaction_discovery",
                object_path=artifact_uri,
                content_hash=self.object_store.sha256_bytes(content),
                size_bytes=len(content),
            )
            for tx in txs:
                evidence = EvidenceService(self.db).create_evidence(
                    case_id=case_id,
                    tx_id=tx.id,
                    source_type="tx_metadata",
                    producer=self.name,
                    claim_key="transaction_in_case_scope",
                    raw_path=artifact_uri,
                    decoded=self._tx_summary(tx),
                    confidence="high" if tx.block_number else "partial",
                )
                evidence_ids.append(evidence.id)
            evidence_ids.extend(extra_evidence_ids)
            if case.seed_type == "alert":
                evidence = EvidenceService(self.db).create_evidence(
                    case_id=case_id,
                    tx_id=None,
                    source_type="external_alert",
                    producer=self.name,
                    claim_key="external_incident_seed",
                    raw_path=artifact_uri,
                    decoded=self._alert_summary(case),
                    confidence="partial",
                )
                evidence_ids.append(evidence.id)
            status = "success" if txs or case.seed_type == "alert" else ("partial" if case.seed_type == "address" else "failed")
            job_service.finish(job, status, output=discovery)
            return WorkerResult(case_id=case_id, worker_name=self.name, status=status, summary=discovery, artifacts=artifacts, evidence_ids=evidence_ids)
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, artifacts=artifacts, evidence_ids=evidence_ids, error=str(exc))

    def _hydrate_seed_transaction(self, case, tx: Transaction) -> None:
        rpc_url, _ = resolve_rpc_url(case.network)
        if not rpc_url or not tx.tx_hash.startswith("0x"):
            return
        try:
            w3 = apply_network_middlewares(Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20})), case.network_key)
            chain_tx = w3.eth.get_transaction(tx.tx_hash)
            receipt = w3.eth.get_transaction_receipt(tx.tx_hash)
            block = w3.eth.get_block(chain_tx["blockNumber"]) if chain_tx.get("blockNumber") is not None else None
            input_data = self._hex(chain_tx.get("input", "0x"))
            tx.block_number = int(chain_tx["blockNumber"]) if chain_tx.get("blockNumber") is not None else None
            tx.block_timestamp = datetime.fromtimestamp(block["timestamp"], timezone.utc) if block else None
            tx.tx_index = int(chain_tx.get("transactionIndex", 0))
            tx.from_address = str(chain_tx.get("from", "")).lower()
            tx.to_address = str(chain_tx.get("to", "")).lower() if chain_tx.get("to") else None
            tx.nonce = int(chain_tx.get("nonce", 0))
            tx.value_wei = int(chain_tx.get("value", 0))
            tx.status = int(receipt.get("status", 0)) if receipt else None
            tx.method_selector = input_data[:10] if input_data and len(input_data) >= 10 else None
            tx.metadata_json = {"input": input_data, "log_count": len(receipt.get("logs", [])) if receipt else 0}
            self.db.add(tx)
            self.db.commit()
            self.db.refresh(tx)
            if receipt:
                receipt_payload = json.loads(Web3.to_json(receipt))
                normalized = EvidenceParserService().normalize_evm_receipt(receipt_payload, tx.tx_hash)
                receipt_content = json.dumps(receipt_payload, indent=2, sort_keys=True, default=str).encode("utf-8")
                receipt_uri = self.object_store.put_bytes(
                    receipt_content,
                    f"cases/{case.id}/discovery/evm_receipt_{tx.tx_hash}.json",
                    "application/json",
                )
                EvidenceService(self.db).create_artifact(
                    case.id,
                    producer=self.name,
                    artifact_type="evm_receipt",
                    object_path=receipt_uri,
                    content_hash=self.object_store.sha256_bytes(receipt_content),
                    size_bytes=len(receipt_content),
                    metadata={"network_key": case.network_key, "tx_hash": tx.tx_hash},
                    tx_id=tx.id,
                )
                EvidenceService(self.db).create_evidence(
                    case_id=case.id,
                    tx_id=tx.id,
                    source_type="receipt_log",
                    producer=self.name,
                    claim_key="evm_receipt_events_normalized",
                    raw_path=receipt_uri,
                    decoded=normalized,
                    confidence="high" if normalized.get("status") == 1 else "partial",
                )
        except Exception:
            return

    def _hydrate_sui_transaction(self, case, tx: Transaction) -> list[str]:
        rpc_url, _ = resolve_rpc_url(case.network)
        if not rpc_url:
            return []
        try:
            result = self._sui_rpc_call(
                rpc_url,
                "sui_getTransactionBlock",
                [
                    tx.tx_hash,
                    {
                        "showInput": True,
                        "showEffects": True,
                        "showEvents": True,
                        "showObjectChanges": True,
                        "showBalanceChanges": True,
                    },
                ],
            )
            summary = self._sui_tx_summary(result)
            content = json.dumps(result, indent=2, sort_keys=True, default=str).encode("utf-8")
            artifact_uri = self.object_store.put_bytes(content, f"cases/{case.id}/discovery/sui_tx_{tx.tx_hash}.json", "application/json")
            EvidenceService(self.db).create_artifact(
                case.id,
                producer=self.name,
                artifact_type="sui_transaction_block",
                object_path=artifact_uri,
                content_hash=self.object_store.sha256_bytes(content),
                size_bytes=len(content),
                metadata={"network_key": case.network_key, "tx_hash": tx.tx_hash},
                tx_id=tx.id,
            )
            tx.block_number = int(result.get("checkpoint")) if result.get("checkpoint") is not None else None
            timestamp_ms = result.get("timestampMs")
            tx.block_timestamp = datetime.fromtimestamp(int(timestamp_ms) / 1000, timezone.utc) if timestamp_ms else None
            tx.tx_index = None
            tx.from_address = summary.get("sender")
            tx.to_address = summary.get("primary_package")
            tx.status = 1 if summary.get("status") == "success" else 0
            tx.method_name = summary.get("primary_call")
            tx.metadata_json = {
                "network_type": "sui",
                "raw_path": artifact_uri,
                "checkpoint": result.get("checkpoint"),
                "timestamp_ms": timestamp_ms,
                "status": summary.get("status"),
                "calls": summary.get("calls", []),
                "events": summary.get("events", []),
                "balance_changes": summary.get("balance_changes", []),
            }
            self.db.add(tx)
            self.db.commit()
            self.db.refresh(tx)
            evidence_ids = []
            tx_evidence = EvidenceService(self.db).create_evidence(
                case_id=case.id,
                tx_id=tx.id,
                source_type="tx_metadata",
                producer=self.name,
                claim_key="sui_transaction_block_verified",
                raw_path=artifact_uri,
                decoded=summary,
                confidence="high" if summary.get("status") == "success" else "partial",
            )
            evidence_ids.append(tx_evidence.id)
            if summary.get("flows"):
                flow_evidence = EvidenceService(self.db).create_evidence(
                    case_id=case.id,
                    tx_id=tx.id,
                    source_type="balance_diff",
                    producer=self.name,
                    claim_key="sui_reward_redemption_flow",
                    raw_path=artifact_uri,
                    decoded={
                        "tx_hash": tx.tx_hash,
                        "flows": summary["flows"],
                        "balance_changes": summary.get("balance_changes", []),
                        "reward_event": summary.get("reward_event"),
                    },
                    confidence="high",
                )
                evidence_ids.append(flow_evidence.id)
            return evidence_ids
        except Exception:
            return []

    def _sui_rpc_call(self, rpc_url: str, method: str, params: list) -> Any:
        response = httpx.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload.get("result") or {}

    def _sui_tx_summary(self, result: dict[str, Any]) -> dict[str, Any]:
        data = ((result.get("transaction") or {}).get("data") or {})
        tx_data = data.get("transaction") or {}
        inputs = tx_data.get("inputs") or []
        commands = tx_data.get("transactions") or []
        effects = result.get("effects") or {}
        sender = data.get("sender")
        calls = []
        for command in commands:
            move_call = command.get("MoveCall") if isinstance(command, dict) else None
            if not move_call:
                continue
            calls.append(
                {
                    "package": move_call.get("package"),
                    "module": move_call.get("module"),
                    "function": move_call.get("function"),
                    "type_arguments": move_call.get("type_arguments") or [],
                }
            )
        events = [
            {
                "type": event.get("type"),
                "package_id": event.get("packageId"),
                "module": event.get("transactionModule"),
                "sender": event.get("sender"),
                "parsed_json": event.get("parsedJson") or {},
            }
            for event in result.get("events") or []
        ]
        reward_event = next(
            (
                event
                for event in events
                if str(event.get("type", "")).endswith("SpoolAccountRedeemRewardsEventV2")
                or "RedeemRewards" in str(event.get("type", ""))
            ),
            None,
        )
        balance_changes = result.get("balanceChanges") or []
        positive_sui = [
            item
            for item in balance_changes
            if item.get("coinType") == "0x2::sui::SUI" and int(item.get("amount") or 0) > 0
        ]
        flows = []
        if reward_event:
            parsed = reward_event.get("parsed_json") or {}
            gross_reward = parsed.get("rewards")
            target = sender
            if positive_sui:
                owner = positive_sui[0].get("owner") or {}
                target = owner.get("AddressOwner") or target
            flows.append(
                {
                    "from": f"rewards_pool:{parsed.get('rewards_pool_id', 'unknown')}",
                    "to": target,
                    "asset": "SUI",
                    "amount": self._sui_amount(gross_reward),
                    "amount_mist": str(gross_reward or ""),
                    "net_amount": self._sui_amount(positive_sui[0].get("amount")) if positive_sui else None,
                    "evidence": "SpoolAccountRedeemRewardsEventV2 + balanceChanges",
                }
            )
        primary = calls[0] if calls else {}
        return {
            "digest": result.get("digest"),
            "checkpoint": result.get("checkpoint"),
            "timestamp_ms": result.get("timestampMs"),
            "sender": sender,
            "status": (effects.get("status") or {}).get("status"),
            "primary_package": primary.get("package"),
            "primary_call": "::".join(str(primary.get(part, "")) for part in ("module", "function")).strip(":") if primary else None,
            "calls": calls,
            "input_count": len(inputs),
            "event_count": len(events),
            "events": events,
            "reward_event": reward_event,
            "balance_changes": balance_changes,
            "flows": flows,
        }

    def _sui_amount(self, mist: Any) -> str | None:
        if mist in {None, ""}:
            return None
        return f"{int(mist) / 1_000_000_000:.9f}".rstrip("0").rstrip(".")

    def _discover_address_txs(self, case) -> list[Transaction]:
        explorer_key, explorer_key_source = resolve_explorer_api_key(case.network)
        if not explorer_key or not case.network.explorer_base_url:
            EvidenceService(self.db).create_evidence(
                case_id=case.id,
                source_type="provider_degradation",
                producer=self.name,
                claim_key="address_discovery_explorer_missing",
                raw_path=None,
                decoded={
                    "address": case.seed_value,
                    "network_key": case.network_key,
                    "explorer_key_source": explorer_key_source,
                    "explorer_base_url": case.network.explorer_base_url,
                    "boundary": "Address seed discovery requires an explorer txlist API key. Public RPC fallback records metadata only and does not fabricate transactions.",
                },
                confidence="partial",
            )
            return []
        response = httpx.get(
            case.network.explorer_base_url,
            params={
                "chainid": case.network.chain_id,
                "module": "account",
                "action": "txlist",
                "address": case.seed_value,
                "sort": "desc",
                "apikey": explorer_key,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        txs: list[Transaction] = []
        for item in (data.get("result") or [])[:50]:
            txs.append(
                CaseService(self.db).add_transaction(
                    case.id,
                    TransactionCreate(
                        tx_hash=item["hash"],
                        phase="discovered",
                        metadata={
                            "method_selector": (item.get("input") or "0x")[:10],
                            "source": "explorer_txlist",
                        },
                    ),
                )
            )
        return txs

    def _tx_summary(self, tx: Transaction) -> dict[str, Any]:
        return {
            "id": tx.id,
            "tx_hash": tx.tx_hash,
            "block_number": tx.block_number,
            "timestamp": tx.block_timestamp.isoformat() if tx.block_timestamp else None,
            "from": tx.from_address,
            "to": tx.to_address,
            "method_selector": tx.method_selector,
            "phase": tx.phase,
            "artifact_status": tx.artifact_status,
        }

    def _alert_summary(self, case) -> dict[str, Any]:
        return {
            "source": case.seed_value,
            "network_key": case.network_key,
            "title": case.title,
            "seed_type": case.seed_type,
        }

    def _hex(self, value: Any) -> str:
        if hasattr(value, "hex"):
            return value.hex()
        return str(value)

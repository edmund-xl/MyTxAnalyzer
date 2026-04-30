from __future__ import annotations

import json
import httpx
from sqlalchemy.orm import Session
from web3 import Web3

from app.core.public_rpc import apply_network_middlewares, public_network_info, resolve_explorer_api_key, resolve_rpc_url
from app.core.object_store import ObjectStore
from app.models.schemas import WorkerResult
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.job_service import JobService


class EnvironmentCheckWorker:
    name = "environment_check_worker"

    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def run(self, case_id: str) -> WorkerResult:
        case = CaseService(self.db).get_case(case_id)
        network = case.network
        input_payload = {"network_key": case.network_key, "seed_value": case.seed_value}
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, input_payload)
        output = {
            "rpc_ok": False,
            "chain_id": None,
            "network_type": getattr(network, "network_type", "evm"),
            "trace_transaction_ok": False,
            "debug_trace_transaction_ok": False,
            "explorer_ok": False,
            "historical_call_ok": False,
            "rpc_source": "missing",
            "explorer_key_source": "missing",
            "capability_matrix": {},
            "public_network_info": public_network_info(case.network_key),
            "degradation_notes": [],
        }
        status = "success"
        try:
            rpc_url, rpc_source = resolve_rpc_url(network)
            output["rpc_source"] = rpc_source
            if not rpc_url:
                output["degradation_notes"].append(f"Missing RPC env {network.rpc_url_secret_ref}")
                status = "partial"
            elif getattr(network, "network_type", "evm") == "sui":
                sui_status = self._sui_rpc_status(rpc_url)
                output.update(sui_status)
                output["chain_id"] = int(network.chain_id)
                output["rpc_ok"] = bool(sui_status.get("chain_identifier") and sui_status.get("latest_checkpoint"))
                output["explorer_ok"] = bool(network.explorer_base_url)
                output["historical_call_ok"] = False
                output["degradation_notes"].append("Sui is non-EVM: eth_chainId, trace_transaction, debug_traceTransaction and TxAnalyzer are not applicable.")
                if not output["rpc_ok"]:
                    status = "partial"
            else:
                w3 = apply_network_middlewares(Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20})), case.network_key)
                output["chain_id"] = int(w3.eth.chain_id)
                output["rpc_ok"] = output["chain_id"] == int(network.chain_id)
                if not output["rpc_ok"]:
                    output["degradation_notes"].append("RPC chain_id does not match configured network")
                    status = "partial"
                try:
                    w3.eth.get_block("latest")
                except Exception as exc:
                    output["rpc_ok"] = False
                    output["degradation_notes"].append(f"Latest block check failed: {exc}")
                    status = "partial"
                trace_target = case.seed_value if case.seed_type == "transaction" and case.seed_value.startswith("0x") else None
                if trace_target is None:
                    transactions = CaseService(self.db).list_transactions(case.id)
                    trace_target = next((tx.tx_hash for tx in transactions if tx.tx_hash.startswith("0x")), None)
                if trace_target:
                    output["trace_target_tx"] = trace_target
                    output["trace_transaction_ok"] = self._rpc_method_ok(w3, "trace_transaction", [trace_target])
                    output["debug_trace_transaction_ok"] = self._rpc_method_ok(w3, "debug_traceTransaction", [trace_target, {}])
                    output["eth_get_transaction_receipt_ok"] = self._rpc_method_ok(w3, "eth_getTransactionReceipt", [trace_target])
                output["historical_call_ok"] = bool(network.supports_historical_eth_call)

            if getattr(network, "network_type", "evm") == "evm":
                explorer_key, explorer_key_source = resolve_explorer_api_key(network)
                output["explorer_key_source"] = explorer_key_source
                if network.explorer_base_url and explorer_key:
                    output["explorer_ok"] = self._explorer_ok(network.explorer_base_url, explorer_key, network.chain_id)
                else:
                    output["degradation_notes"].append("Explorer API key or base URL missing")
                    status = "partial"

            output["capability_matrix"] = {
                "eth_chainId": bool(output.get("chain_id")),
                "eth_getTransactionReceipt": bool(output.get("eth_get_transaction_receipt_ok") or output.get("network_type") == "sui"),
                "trace_transaction": bool(output.get("trace_transaction_ok")),
                "debug_traceTransaction": bool(output.get("debug_trace_transaction_ok")),
                "explorer_txlist_getsourcecode": bool(output.get("explorer_ok")),
                "historical_eth_call": bool(output.get("historical_call_ok")),
            }

            artifact_key = f"cases/{case_id}/environment/capability.json"
            artifact_uri = self.object_store.put_bytes(
                json.dumps(output, indent=2, sort_keys=True).encode("utf-8"),
                artifact_key,
                "application/json",
            )
            EvidenceService(self.db).create_artifact(
                case_id,
                producer=self.name,
                artifact_type="environment_check",
                object_path=artifact_uri,
                content_hash=self.object_store.sha256_bytes(json.dumps(output, sort_keys=True).encode("utf-8")),
                size_bytes=len(json.dumps(output).encode("utf-8")),
                metadata={"network_key": case.network_key},
            )
            evidence = EvidenceService(self.db).create_evidence(
                case_id=case_id,
                source_type="artifact_summary",
                producer=self.name,
                claim_key="environment_capability",
                raw_path=artifact_uri,
                decoded=output,
                confidence="high" if status == "success" else "partial",
            )
            job_service.finish(job, status, output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status=status, summary=output, artifacts=[artifact_uri], evidence_ids=[evidence.id])
        except Exception as exc:
            job_service.finish(job, "failed", output=output, error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary=output, error=str(exc))

    def _rpc_method_ok(self, w3: Web3, method: str, params: list) -> bool:
        try:
            response = w3.provider.make_request(method, params)
            return "error" not in response
        except Exception:
            return False

    def _sui_rpc_status(self, rpc_url: str) -> dict:
        def call(method: str, params: list | None = None):
            response = httpx.post(
                rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return payload.get("result")

        try:
            return {
                "chain_identifier": call("sui_getChainIdentifier"),
                "latest_checkpoint": call("sui_getLatestCheckpointSequenceNumber"),
            }
        except Exception as exc:
            return {"chain_identifier": None, "latest_checkpoint": None, "sui_rpc_error": str(exc)}

    def _explorer_ok(self, base_url: str, api_key: str, chain_id: int) -> bool:
        try:
            response = httpx.get(
                base_url,
                params={"chainid": chain_id, "module": "proxy", "action": "eth_blockNumber", "apikey": api_key},
                timeout=15,
            )
            return response.status_code < 500
        except Exception:
            return False

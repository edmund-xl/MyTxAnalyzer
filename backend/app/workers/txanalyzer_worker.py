from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.object_store import ObjectStore
from app.core.public_rpc import resolve_rpc_url
from app.models.db import Transaction
from app.services.evidence_service import EvidenceService
from app.services.job_service import JobService


class TxAnalyzerJobInput(BaseModel):
    case_id: str
    network_key: str
    tx_hash: str
    timeout_seconds: int = 120
    skip_opcode: bool = False


class TxAnalyzerJobOutput(BaseModel):
    case_id: str
    tx_hash: str
    status: Literal["success", "partial", "failed"]
    local_artifact_dir: str | None = None
    object_store_prefix: str | None = None
    files_imported: int = 0
    manifest_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    error: str | None = None
    evidence_ids: list[str] = []


class TxAnalyzerWorker:
    name = "txanalyzer_worker"

    def __init__(
        self,
        db: Session,
        object_store: ObjectStore | None = None,
        txanalyzer_root: str | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()
        self.root = Path(txanalyzer_root or settings.txanalyzer_root)
        self.python_executable = self._resolve_python_executable(python_executable or settings.txanalyzer_python or sys.executable)

    def run(self, job: TxAnalyzerJobInput) -> TxAnalyzerJobOutput:
        job_service = JobService(self.db)
        job_run = job_service.start(job.case_id, self.name, job.model_dump())
        tx = self.db.scalar(select(Transaction).where(Transaction.case_id == job.case_id, Transaction.tx_hash == job.tx_hash.lower()))
        try:
            cached = self._try_cache_hit(job, tx.id if tx else None)
            if cached:
                if tx:
                    tx.artifact_status = "partial" if cached.status == "partial" else "done"
                    self.db.add(tx)
                    self.db.commit()
                job_service.finish(job_run, cached.status, output=cached.model_dump())
                return cached
            if not self.root.exists():
                raise FileNotFoundError(f"TxAnalyzer root not found: {self.root}")
            self._write_txanalyzer_config(job.network_key)
            cmd = [
                self.python_executable,
                "scripts/pull_artifacts.py",
                "--network",
                job.network_key,
                "--tx",
                job.tx_hash,
                "--timeout",
                str(job.timeout_seconds),
            ]
            if job.skip_opcode:
                cmd.append("--skip-opcode")
            proc = subprocess.run(cmd, cwd=self.root, text=True, capture_output=True, timeout=job.timeout_seconds + 30)
            stdout_uri, stderr_uri = self._store_execution_logs(job.case_id, job.tx_hash, proc.stdout, proc.stderr)
            tx_dir = self.root / "transactions" / job.tx_hash
            fallback_reason: str | None = None
            if proc.returncode != 0:
                try:
                    fallback_reason = self._build_rpc_fallback_artifacts(job, tx_dir)
                except Exception as fallback_exc:
                    error_tail = proc.stderr[-2000:] or proc.stdout[-2000:] or f"TxAnalyzer exited with {proc.returncode}"
                    raise RuntimeError(f"{error_tail}; RPC fallback failed: {fallback_exc}") from fallback_exc
            if not tx_dir.exists():
                raise FileNotFoundError(f"TxAnalyzer artifact directory missing: {tx_dir}")

            manifest = self._build_manifest(tx_dir, job)
            if fallback_reason:
                manifest["fallback_reason"] = fallback_reason
                manifest["cli_returncode"] = proc.returncode
            imported_paths = self._import_directory(job.case_id, job.tx_hash, tx_dir, tx.id if tx else None)
            manifest["files_imported"] = len(imported_paths)
            manifest_content = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
            manifest_uri = self.object_store.put_bytes(
                manifest_content,
                f"cases/{job.case_id}/transactions/{job.tx_hash}/txanalyzer/workbench_manifest.json",
                "application/json",
            )
            EvidenceService(self.db).create_artifact(
                job.case_id,
                producer=self.name,
                artifact_type="manifest",
                object_path=manifest_uri,
                content_hash=self.object_store.sha256_bytes(manifest_content),
                size_bytes=len(manifest_content),
                tx_id=tx.id if tx else None,
            )
            evidence_ids = self._create_artifact_evidence(job, tx.id if tx else None, manifest_uri, manifest)
            if tx:
                tx.artifact_status = "partial" if fallback_reason else "done"
                self.db.add(tx)
                self.db.commit()
            self._write_cache(job)
            output_status: Literal["success", "partial"] = "partial" if fallback_reason else "success"
            output = TxAnalyzerJobOutput(
                case_id=job.case_id,
                tx_hash=job.tx_hash,
                status=output_status,
                local_artifact_dir=str(tx_dir),
                object_store_prefix=f"cases/{job.case_id}/transactions/{job.tx_hash}/txanalyzer/",
                files_imported=len(imported_paths),
                manifest_path=manifest_uri,
                stdout_path=stdout_uri,
                stderr_path=stderr_uri,
                error=fallback_reason,
                evidence_ids=evidence_ids,
            )
            job_service.finish(job_run, output_status, output=output.model_dump())
            return output
        except Exception as exc:
            if tx:
                tx.artifact_status = "failed"
                self.db.add(tx)
                self.db.commit()
            output = TxAnalyzerJobOutput(case_id=job.case_id, tx_hash=job.tx_hash, status="failed", error=str(exc))
            job_service.finish(job_run, "failed", output=output.model_dump(), error=str(exc))
            return output

    def _write_txanalyzer_config(self, network_key: str) -> None:
        from app.services.network_service import NetworkService

        network = NetworkService(self.db).get_network(network_key)
        if network is None:
            raise ValueError(f"Unknown network {network_key}")
        rpc_url, rpc_source = resolve_rpc_url(network)
        if not rpc_url:
            raise ValueError(f"Missing RPC env {network.rpc_url_secret_ref}")
        explorer_key = os.getenv(network.explorer_api_key_secret_ref or "") or ""
        config = {
            "networks": {
                network_key: {
                    "name": network.name,
                    "rpc_url": rpc_url,
                    "rpc_source": rpc_source,
                    "etherscan_api_key": explorer_key,
                    "etherscan_base_url": network.explorer_base_url,
                    "chain_id": network.chain_id,
                }
            },
            "default_network": network_key,
        }
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    def _resolve_python_executable(self, value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            return str(path)
        resolved = path.resolve()
        if resolved.exists():
            return str(resolved)
        backend_relative = settings.project_root / "backend" / path
        if backend_relative.exists():
            return str(backend_relative)
        project_relative = settings.project_root / path
        if project_relative.exists():
            return str(project_relative)
        return value

    def _store_execution_logs(self, case_id: str, tx_hash: str, stdout: str, stderr: str) -> tuple[str, str]:
        prefix = f"cases/{case_id}/transactions/{tx_hash}/txanalyzer/execution"
        stdout_uri = self.object_store.put_bytes(stdout.encode("utf-8"), f"{prefix}/stdout.log", "text/plain")
        stderr_uri = self.object_store.put_bytes(stderr.encode("utf-8"), f"{prefix}/stderr.log", "text/plain")
        EvidenceService(self.db).create_artifact(case_id, self.name, "execution_log", stdout_uri, self.object_store.sha256_bytes(stdout.encode("utf-8")), len(stdout.encode("utf-8")))
        EvidenceService(self.db).create_artifact(case_id, self.name, "execution_log", stderr_uri, self.object_store.sha256_bytes(stderr.encode("utf-8")), len(stderr.encode("utf-8")))
        return stdout_uri, stderr_uri

    def _try_cache_hit(self, job: TxAnalyzerJobInput, tx_id: str | None) -> TxAnalyzerJobOutput | None:
        cache_prefix = self._cache_prefix(job)
        keys = self.object_store.list_prefix(cache_prefix)
        if not keys or not any(key.endswith("workbench_manifest.json") for key in keys):
            return None
        case_prefix = self._case_prefix(job)
        evidence_service = EvidenceService(self.db)
        imported_paths: list[str] = []
        manifest_uri: str | None = None
        for key in keys:
            rel = key.removeprefix(cache_prefix)
            target_key = f"{case_prefix}{rel}"
            content = self.object_store.get_bytes(key)
            uri = self.object_store.put_bytes(content, target_key)
            imported_paths.append(uri)
            if rel == "workbench_manifest.json":
                manifest_uri = uri
                continue
            evidence_service.create_artifact(
                job.case_id,
                producer=self.name,
                artifact_type=self._guess_artifact_type(rel),
                object_path=uri,
                content_hash=self.object_store.sha256_bytes(content),
                size_bytes=len(content),
                metadata={"relative_path": rel, "cache_hit": True},
                tx_id=tx_id,
            )
        if not manifest_uri:
            return None
        manifest = json.loads(self.object_store.get_bytes(manifest_uri).decode("utf-8"))
        manifest["cache_hit"] = True
        manifest["object_prefix"] = case_prefix
        manifest["files_imported"] = max(0, len(imported_paths) - 1)
        manifest_content = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        manifest_uri = self.object_store.put_bytes(manifest_content, f"{case_prefix}workbench_manifest.json", "application/json")
        evidence_service.create_artifact(
            job.case_id,
            producer=self.name,
            artifact_type="manifest",
            object_path=manifest_uri,
            content_hash=self.object_store.sha256_bytes(manifest_content),
            size_bytes=len(manifest_content),
            metadata={"cache_hit": True},
            tx_id=tx_id,
        )
        evidence_ids = self._create_artifact_evidence(job, tx_id, manifest_uri, manifest)
        stdout_uri, stderr_uri = self._store_execution_logs(job.case_id, job.tx_hash, f"TxAnalyzer cache hit: {cache_prefix}\n", "")
        output_status: Literal["success", "partial"] = "partial" if manifest.get("fallback_reason") else "success"
        return TxAnalyzerJobOutput(
            case_id=job.case_id,
            tx_hash=job.tx_hash,
            status=output_status,
            object_store_prefix=case_prefix,
            files_imported=manifest["files_imported"],
            manifest_path=manifest_uri,
            stdout_path=stdout_uri,
            stderr_path=stderr_uri,
            evidence_ids=evidence_ids,
        )

    def _write_cache(self, job: TxAnalyzerJobInput) -> None:
        case_prefix = self._case_prefix(job)
        cache_prefix = self._cache_prefix(job)
        for key in self.object_store.list_prefix(case_prefix):
            rel = key.removeprefix(case_prefix)
            self.object_store.copy_object(key, f"{cache_prefix}{rel}")

    def _case_prefix(self, job: TxAnalyzerJobInput) -> str:
        return f"cases/{job.case_id}/transactions/{job.tx_hash}/txanalyzer/"

    def _cache_prefix(self, job: TxAnalyzerJobInput) -> str:
        return f"txanalyzer-cache/{job.network_key}/{job.tx_hash}/"

    def _import_directory(self, case_id: str, tx_hash: str, tx_dir: Path, tx_id: str | None) -> list[str]:
        imported: list[str] = []
        evidence_service = EvidenceService(self.db)
        for path in tx_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(tx_dir).as_posix()
            object_key = f"cases/{case_id}/transactions/{tx_hash}/txanalyzer/{rel}"
            uri = self.object_store.put_file(path, object_key)
            imported.append(uri)
            evidence_service.create_artifact(
                case_id,
                producer=self.name,
                artifact_type=self._guess_artifact_type(rel),
                object_path=uri,
                content_hash=self._sha256(path),
                size_bytes=path.stat().st_size,
                metadata={"relative_path": rel},
                tx_id=tx_id,
            )
        return imported

    def _build_manifest(self, tx_dir: Path, job: TxAnalyzerJobInput) -> dict:
        files = []
        for path in tx_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(tx_dir).as_posix()
            files.append({"path": rel, "sha256": self._sha256(path), "size_bytes": path.stat().st_size, "artifact_type": self._guess_artifact_type(rel)})
        return {
            "producer": self.name,
            "tx_hash": job.tx_hash,
            "network_key": job.network_key,
            "source_dir": str(tx_dir),
            "object_prefix": f"cases/{job.case_id}/transactions/{job.tx_hash}/txanalyzer/",
            "files": files,
        }

    def _create_artifact_evidence(self, job: TxAnalyzerJobInput, tx_id: str | None, manifest_uri: str, manifest: dict) -> list[str]:
        files = manifest["files"]
        types = {item["artifact_type"] for item in files}
        evidence = EvidenceService(self.db).create_evidence(
            case_id=job.case_id,
            tx_id=tx_id,
            source_type="artifact_summary",
            producer=self.name,
            claim_key="txanalyzer_artifacts_available",
            raw_path=manifest_uri,
            decoded={
                "tx_hash": job.tx_hash,
                "has_trace": "trace" in types,
                "has_source": "source" in types,
                "has_opcode": "opcode" in types,
                "has_receipt": "receipt" in types,
                "has_tx_metadata": "tx_metadata" in types,
                "file_count": len(files),
                "fallback_reason": manifest.get("fallback_reason"),
            },
            confidence="medium" if manifest.get("fallback_reason") else "high",
        )
        evidence_ids = [evidence.id]
        if job.skip_opcode or "opcode" not in types:
            partial = EvidenceService(self.db).create_evidence(
                case_id=job.case_id,
                tx_id=tx_id,
                source_type="artifact_summary",
                producer=self.name,
                claim_key="opcode_trace_unavailable",
                raw_path=manifest_uri,
                decoded={"reason": "debug_traceTransaction unavailable or --skip-opcode used"},
                confidence="partial",
            )
            evidence_ids.append(partial.id)
        return evidence_ids

    def _build_rpc_fallback_artifacts(self, job: TxAnalyzerJobInput, tx_dir: Path) -> str:
        rpc_url = self._rpc_url_for_network(job.network_key)
        if tx_dir.exists():
            shutil.rmtree(tx_dir)
        (tx_dir / "metadata").mkdir(parents=True, exist_ok=True)
        (tx_dir / "receipt").mkdir(parents=True, exist_ok=True)

        tx_payload = self._rpc_call(rpc_url, "eth_getTransactionByHash", [job.tx_hash], timeout=20)
        receipt_payload = self._rpc_call(rpc_url, "eth_getTransactionReceipt", [job.tx_hash], timeout=20)
        if not tx_payload or not receipt_payload:
            raise RuntimeError("eth_getTransactionByHash or eth_getTransactionReceipt returned empty result")

        self._write_json(tx_dir / "metadata" / "transaction.json", tx_payload)
        self._write_json(tx_dir / "receipt" / "receipt.json", receipt_payload)

        opcode_note = "debug_traceTransaction was skipped"
        if not job.skip_opcode:
            (tx_dir / "opcode").mkdir(parents=True, exist_ok=True)
            try:
                opcode_payload = self._rpc_call(
                    rpc_url,
                    "debug_traceTransaction",
                    [
                        job.tx_hash,
                        {
                            "disableStorage": True,
                            "disableStack": True,
                            "disableMemory": True,
                            "enableReturnData": True,
                        },
                    ],
                    timeout=job.timeout_seconds,
                )
                self._write_json(tx_dir / "opcode" / "debug_traceTransaction.json", opcode_payload)
                opcode_note = "debug_traceTransaction artifact imported"
            except Exception as exc:
                opcode_note = f"debug_traceTransaction unavailable: {exc}"
                self._write_json(tx_dir / "opcode" / "debug_traceTransaction_error.json", {"error": str(exc)})

        readme = "\n".join(
            [
                "## TxAnalyzer RPC Fallback Artifacts",
                "",
                f"- network: `{job.network_key}`",
                f"- tx_hash: `{job.tx_hash}`",
                "- CLI status: failed before trace import, so the workbench fetched deterministic JSON-RPC artifacts directly.",
                "- reason: `trace_transaction` is unavailable on this RPC or the CLI could not parse its trace response.",
                f"- opcode: {opcode_note}",
                "",
                "### Files",
                "- `metadata/transaction.json`: eth_getTransactionByHash",
                "- `receipt/receipt.json`: eth_getTransactionReceipt",
                "- `opcode/debug_traceTransaction.json`: opcode-level trace when available",
            ]
        )
        (tx_dir / "README.md").write_text(readme, encoding="utf-8")
        return "TxAnalyzer CLI failed before trace import; imported eth_getTransactionByHash, eth_getTransactionReceipt and debug_traceTransaction fallback artifacts."

    def _rpc_url_for_network(self, network_key: str) -> str:
        from app.services.network_service import NetworkService

        network = NetworkService(self.db).get_network(network_key)
        if network is None:
            raise ValueError(f"Unknown network {network_key}")
        rpc_url, _ = resolve_rpc_url(network)
        if not rpc_url:
            raise ValueError(f"Missing RPC env {network.rpc_url_secret_ref}")
        return rpc_url

    def _rpc_call(self, rpc_url: str, method: str, params: list, timeout: int) -> dict:
        response = httpx.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            headers={"content-type": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload.get("result")

    def _write_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")

    def _sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _guess_artifact_type(rel_path: str) -> str:
        lower = rel_path.lower()
        if "opcode" in lower:
            return "opcode"
        if "trace" in lower:
            return "trace"
        if "receipt" in lower:
            return "receipt"
        if "metadata/transaction" in lower:
            return "tx_metadata"
        if "source" in lower or lower.endswith((".sol", ".vy")):
            return "source"
        if "contracts" in lower:
            return "contract_metadata"
        if "result.md" in lower:
            return "txanalyzer_analysis"
        if "readme" in lower:
            return "artifact_readme"
        if "report" in lower:
            return "tx_report"
        if "stdout" in lower or "stderr" in lower:
            return "execution_log"
        return "unknown"

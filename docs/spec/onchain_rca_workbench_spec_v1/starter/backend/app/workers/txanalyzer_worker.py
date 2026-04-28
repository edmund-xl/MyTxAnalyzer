"""TxAnalyzer integration worker skeleton.

Codex must implement this according to docs/07_TXANALYZER_INTEGRATION.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

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

class TxAnalyzerWorker:
    def __init__(self, txanalyzer_root: str = "/opt/txanalyzer") -> None:
        self.root = Path(txanalyzer_root)

    def run(self, job: TxAnalyzerJobInput) -> TxAnalyzerJobOutput:
        if not self.root.exists():
            return TxAnalyzerJobOutput(case_id=job.case_id, tx_hash=job.tx_hash, status="failed", error="TxAnalyzer root not found")

        cmd = ["python", "scripts/pull_artifacts.py", "--network", job.network_key, "--tx", job.tx_hash, "--timeout", str(job.timeout_seconds)]
        if job.skip_opcode:
            cmd.append("--skip-opcode")

        proc = subprocess.run(cmd, cwd=self.root, text=True, capture_output=True, timeout=job.timeout_seconds + 30)
        tx_dir = self.root / "transactions" / job.tx_hash
        if proc.returncode != 0 or not tx_dir.exists():
            return TxAnalyzerJobOutput(
                case_id=job.case_id,
                tx_hash=job.tx_hash,
                status="failed",
                stdout_path=None,
                stderr_path=None,
                error=proc.stderr[-2000:],
            )

        # TODO: upload directory to S3/MinIO and create DB artifacts.
        manifest = self._build_local_manifest(tx_dir, job)
        manifest_path = tx_dir / "workbench_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return TxAnalyzerJobOutput(
            case_id=job.case_id,
            tx_hash=job.tx_hash,
            status="success",
            local_artifact_dir=str(tx_dir),
            files_imported=len(manifest["files"]),
            manifest_path=str(manifest_path),
        )

    def _build_local_manifest(self, tx_dir: Path, job: TxAnalyzerJobInput) -> dict:
        files = []
        for path in tx_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(tx_dir).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append({"path": rel, "sha256": digest, "size_bytes": path.stat().st_size, "artifact_type": self._guess_artifact_type(rel)})
        return {"producer": "txanalyzer_worker", "tx_hash": job.tx_hash, "network_key": job.network_key, "source_dir": str(tx_dir), "object_prefix": f"cases/{job.case_id}/transactions/{job.tx_hash}/txanalyzer/", "files": files}

    @staticmethod
    def _guess_artifact_type(rel_path: str) -> str:
        lower = rel_path.lower()
        if "trace" in lower:
            return "trace"
        if "opcode" in lower:
            return "opcode"
        if "source" in lower or lower.endswith((".sol", ".vy")):
            return "source"
        if "result.md" in lower:
            return "txanalyzer_analysis"
        if "report" in lower:
            return "tx_report"
        return "unknown"

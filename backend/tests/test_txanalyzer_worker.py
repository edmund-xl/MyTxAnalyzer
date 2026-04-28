from __future__ import annotations

import sys
from pathlib import Path

from app.core.object_store import ObjectStore
from app.models.schemas import CaseCreate, SeedType, AnalysisDepth, TransactionCreate
from app.services.case_service import CaseService
from app.workers.txanalyzer_worker import TxAnalyzerJobInput, TxAnalyzerWorker


def test_txanalyzer_worker_invokes_cli_and_imports_artifacts(tmp_path, db_session):
    root = tmp_path / "txanalyzer"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "pull_artifacts.py"
    script.write_text(
        """
import argparse
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument("--network")
parser.add_argument("--tx")
parser.add_argument("--timeout")
parser.add_argument("--skip-opcode", action="store_true")
args = parser.parse_args()
tx_dir = Path("transactions") / args.tx
(tx_dir / "trace").mkdir(parents=True, exist_ok=True)
(tx_dir / "trace" / "call_trace.json").write_text('{"ok": true}')
print("pulled", args.tx)
""",
        encoding="utf-8",
    )

    case_service = CaseService(db_session)
    case = case_service.create_case(
        CaseCreate(
            network_key="megaeth",
            seed_type=SeedType.transaction,
            seed_value="0x" + "c" * 64,
            depth=AnalysisDepth.full,
        ),
        "test",
    )
    tx = case_service.add_transaction(case.id, TransactionCreate(tx_hash=case.seed_value, phase="seed"))
    store = ObjectStore(mode="local", local_root=tmp_path / "artifacts")
    result = TxAnalyzerWorker(db_session, object_store=store, txanalyzer_root=str(root), python_executable=sys.executable).run(
        TxAnalyzerJobInput(case_id=case.id, network_key="megaeth", tx_hash=tx.tx_hash, skip_opcode=True)
    )

    assert result.status == "success", result.error
    assert result.files_imported >= 1
    assert result.manifest_path
    assert store.list_prefix(f"cases/{case.id}/transactions/{tx.tx_hash}/txanalyzer")

    script.write_text("raise SystemExit(9)\n", encoding="utf-8")
    second_case = case_service.create_case(
        CaseCreate(
            network_key="megaeth",
            seed_type=SeedType.transaction,
            seed_value=case.seed_value,
            depth=AnalysisDepth.full,
        ),
        "test",
    )
    second_tx = case_service.add_transaction(second_case.id, TransactionCreate(tx_hash=case.seed_value, phase="seed"))
    cached = TxAnalyzerWorker(db_session, object_store=store, txanalyzer_root=str(root), python_executable=sys.executable).run(
        TxAnalyzerJobInput(case_id=second_case.id, network_key="megaeth", tx_hash=second_tx.tx_hash, skip_opcode=True)
    )

    assert cached.status == "success", cached.error
    assert cached.manifest_path
    assert "cache hit" in store.get_bytes(cached.stdout_path).decode("utf-8")

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.core.config import settings
from app.models.schemas import TxAnalyzerRuntimeHealth


class TxAnalyzerRuntimeService:
    required_packages = ("requests", "pandas", "tqdm", "web3")

    def check(self) -> TxAnalyzerRuntimeHealth:
        root = Path(settings.txanalyzer_root)
        script = root / "scripts" / "pull_artifacts.py"
        python_executable = settings.txanalyzer_python or sys.executable
        package_status = dict.fromkeys(self.required_packages, False)
        python_ok = False
        error = None

        try:
            proc = subprocess.run(
                [
                    python_executable,
                    "-c",
                    self._package_check_code(),
                ],
                text=True,
                capture_output=True,
                timeout=10,
            )
            python_ok = proc.returncode == 0
            if proc.stdout:
                parsed = json.loads(proc.stdout)
                package_status = {package: bool(parsed.get(package)) for package in self.required_packages}
            if proc.returncode != 0:
                error = (proc.stderr or proc.stdout).strip() or f"Python exited with {proc.returncode}"
        except Exception as exc:
            error = str(exc)

        ready = root.exists() and script.exists() and python_ok and all(package_status.values())
        return TxAnalyzerRuntimeHealth(
            ready=ready,
            root=str(root),
            root_exists=root.exists(),
            script_exists=script.exists(),
            python_executable=python_executable,
            python_ok=python_ok,
            required_packages=package_status,
            error=error,
        )

    def _package_check_code(self) -> str:
        packages = json.dumps(self.required_packages)
        return (
            "import importlib.util, json; "
            f"packages = {packages}; "
            "print(json.dumps({name: importlib.util.find_spec(name) is not None for name in packages}))"
        )

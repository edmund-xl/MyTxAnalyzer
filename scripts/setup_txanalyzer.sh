#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${ROOT_DIR}/vendor/txanalyzer"

if [ -d "${TARGET}/.git" ]; then
  git -C "${TARGET}" pull --ff-only
else
  git clone https://github.com/BradMoonUESTC/TxAnalyzer.git "${TARGET}"
fi

echo "TxAnalyzer is available at ${TARGET}"
echo "Docker Compose mounts it into containers as /opt/txanalyzer"

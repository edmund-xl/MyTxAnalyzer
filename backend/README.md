# Backend

## 中文

RCA Workbench 的 FastAPI 后端。

### 本地启动

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench/backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

前端需要使用：

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100/api
```

### 关键环境变量

- `DATABASE_URL`：本地开发当前使用 SQLite；compose 使用 PostgreSQL。
- `OBJECT_STORE_MODE`：本地 artifact 使用 `local`；compose 使用 MinIO。
- `LOCAL_ARTIFACT_ROOT`：本地 artifact 目录。
- `WORKFLOW_MODE`：本地使用 `inline`；Temporal 编排使用 `temporal`。
- `TXANALYZER_ROOT`：本地 TxAnalyzer checkout 目录。
- `TXANALYZER_PYTHON`：调用 TxAnalyzer 的 Python 解释器。
- `ETH_RPC_URL`、`BSC_RPC_URL`、`ARBITRUM_RPC_URL`、`BASE_RPC_URL`、`UNICHAIN_RPC_URL`、`TAIKO_RPC_URL`、`SUI_RPC_URL`：用于 smoke run 的非敏感 RPC endpoint。

不要提交 RPC key、Explorer key、LLM key、数据库密码或对象存储密钥。

### 回归测试

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench/backend
./.venv/bin/pytest -q
```

当前测试覆盖 health、network seed、case CRUD、case detail summary、finding review、report generation、PDF export download、alert seed discovery、Sui native discovery，以及 TxAnalyzer artifact import/cache 行为。

## English

FastAPI backend for the RCA Workbench.

### Local Run

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench/backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

The frontend expects:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100/api
```

### Important Environment Variables

- `DATABASE_URL`: local development currently uses SQLite; compose uses PostgreSQL.
- `OBJECT_STORE_MODE`: `local` for local artifacts; MinIO in compose.
- `LOCAL_ARTIFACT_ROOT`: local artifact folder.
- `WORKFLOW_MODE`: `inline` locally; `temporal` for Temporal-backed orchestration.
- `TXANALYZER_ROOT`: local TxAnalyzer checkout.
- `TXANALYZER_PYTHON`: Python interpreter used to invoke TxAnalyzer.
- `ETH_RPC_URL`, `BSC_RPC_URL`, `ARBITRUM_RPC_URL`, `BASE_RPC_URL`, `UNICHAIN_RPC_URL`, `TAIKO_RPC_URL`, `SUI_RPC_URL`: non-secret RPC endpoints for smoke runs.

Do not commit RPC keys, explorer keys, LLM keys, database passwords, or object-store secrets.

### Regression

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench/backend
./.venv/bin/pytest -q
```

Current tests cover health, network seed, case CRUD, case detail summary, finding review, report generation, PDF export download, alert seed discovery, Sui native discovery, and TxAnalyzer artifact import/cache behavior.

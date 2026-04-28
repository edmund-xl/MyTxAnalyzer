# CODEx_START_HERE — 给 Codex 的实现指令

你要实现的是一个内部使用的“事后链上攻击分析与报告生成工作台”，不是实时监控系统。

## 必须遵守的实现边界

1. 不实现全链实时检测。
2. 不实现 mempool 监控。
3. 不自动发布报告。
4. 所有报告必须先进入 Review 状态。
5. TxAnalyzer 是核心依赖，必须实现 `TxAnalyzerWorker`。
6. 系统第一版只支持 EVM；Solana 暂不实现。
7. 第一版支持 `seed_type = transaction | address | contract | alert`，但 P0 优先 transaction/address。
8. 所有关键结论都必须绑定 evidence_id。
9. 所有外部调用必须有 retry、timeout、error logging 和 artifact 保存。
10. 不要把 RPC key / explorer key 写入代码；从环境变量或 secret store 读取。

## 固定技术栈

### Backend

- Python 3.11+
- FastAPI
- SQLAlchemy 2.x
- Alembic
- PostgreSQL
- Temporal Python SDK for workflow orchestration
- Redis only for cache/rate limit, not as primary workflow state
- MinIO/S3 for raw artifacts
- Pydantic v2
- Web3.py / eth-account / eth-keys

### Frontend

- Next.js 14+
- TypeScript
- React
- shadcn/ui
- TanStack Query
- React Flow for graphs
- Monaco Editor for source/JSON/trace viewing

### External tools

- TxAnalyzer checked out as a Git submodule or mounted dependency under `/opt/txanalyzer`.
- Foundry optional in P1; do not block MVP on replay.

## First implementation target

Implement the MVP backend and enough frontend to run a manual case:

1. User creates a case with network + seed tx.
2. Backend runs environment check.
3. Backend discovers related transactions.
4. Backend invokes TxAnalyzer for each transaction.
5. Backend imports artifact manifests.
6. Backend builds timeline and evidence.
7. Backend generates findings draft.
8. User can review findings.
9. User can generate report markdown.

## Required backend modules

Create these packages:

```text
backend/app
├── api
│   ├── cases.py
│   ├── evidence.py
│   ├── findings.py
│   ├── reports.py
│   └── networks.py
├── core
│   ├── config.py
│   ├── database.py
│   ├── object_store.py
│   ├── logging.py
│   └── security.py
├── models
│   ├── db.py
│   └── schemas.py
├── services
│   ├── case_service.py
│   ├── evidence_service.py
│   ├── report_service.py
│   └── chain_adapter.py
├── workers
│   ├── environment_check_worker.py
│   ├── tx_discovery_worker.py
│   ├── txanalyzer_worker.py
│   ├── decode_worker.py
│   ├── proxy_resolver_worker.py
│   ├── acl_forensics_worker.py
│   ├── safe_forensics_worker.py
│   ├── fund_flow_worker.py
│   ├── loss_calculator_worker.py
│   ├── rca_agent_worker.py
│   └── report_worker.py
└── workflows
    └── case_analysis_workflow.py
```

## Required API endpoints

Implement endpoints exactly as defined in `api/openapi.yaml`.

P0 endpoints:

- `POST /api/cases`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `POST /api/cases/{case_id}/run`
- `GET /api/cases/{case_id}/timeline`
- `GET /api/cases/{case_id}/evidence`
- `GET /api/cases/{case_id}/findings`
- `PATCH /api/findings/{finding_id}/review`
- `POST /api/cases/{case_id}/reports`
- `GET /api/cases/{case_id}/reports/{report_id}`
- `GET /api/networks`

## Required DB schema

Use `db/schema.sql` as the source of truth for schema design. Generate Alembic migrations from this schema.

## Required worker behavior

Each worker must:

1. Read input from workflow payload.
2. Write raw outputs to artifact store.
3. Insert structured rows into PostgreSQL.
4. Return a typed Pydantic object.
5. Add `job_runs` row with start/end/status/error.
6. Never silently swallow errors.
7. Mark partial evidence if a data source is unavailable.

## TxAnalyzer dependency

Do not reimplement TxAnalyzer in MVP. Invoke it as an external CLI:

```bash
cd /opt/txanalyzer
python scripts/pull_artifacts.py --network <network_key> --tx <tx_hash> --timeout 120
```

Then import:

```text
/opt/txanalyzer/transactions/<tx_hash>/
```

into:

```text
s3://<bucket>/cases/<case_id>/transactions/<tx_hash>/txanalyzer/
```

The integration contract is in `docs/07_TXANALYZER_INTEGRATION.md`.

## MVP acceptance checklist

The MVP is accepted only if all are true:

- Can create a case.
- Can run a case workflow to completion on at least one EVM transaction.
- TxAnalyzer artifacts are pulled and stored.
- Timeline shows at least decoded top-level transactions.
- Evidence table contains structured evidence with source type and raw path.
- Findings table shows confidence and reviewer status.
- Report markdown can be generated from findings.
- Reviewer can approve/reject findings.
- All major operations are logged and reproducible.


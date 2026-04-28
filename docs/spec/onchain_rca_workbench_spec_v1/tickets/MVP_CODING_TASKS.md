# MVP Coding Tasks for Codex

## Epic A — Backend scaffold

### A1 FastAPI app

Implement:

- `GET /api/health`
- app config loading
- structured logging
- CORS for local frontend

Acceptance:

- `uvicorn app.main:app --reload` starts.
- `/api/health` returns `{ "status": "ok" }`.

### A2 Database

Implement SQLAlchemy models matching `db/schema.sql`.

Acceptance:

- Alembic migration creates tables.
- Unit test inserts network + case.

### A3 Object store

Implement MinIO/S3 wrapper:

- put_file
- put_bytes
- get_file
- list_prefix
- sha256

Acceptance:

- Upload and list artifact in test.

## Epic B — Case API

### B1 Create/list/get cases

Implement endpoints:

- POST /api/cases
- GET /api/cases
- GET /api/cases/{case_id}

Acceptance:

- Request validates seed_type.
- Creates case status CREATED.

### B2 Run workflow

Implement:

- POST /api/cases/{case_id}/run

Acceptance:

- Starts Temporal workflow or mock workflow in dev mode.

## Epic C — Workers

### C1 EnvironmentCheckWorker

Acceptance:

- Calls eth_chainId.
- Stores job run.
- Writes capability output.

### C2 TxDiscoveryWorker

Acceptance:

- For seed transaction, stores seed transaction row.
- For seed address, stores txlist rows if explorer configured.
- At minimum, no txlist available still stores seed tx.

### C3 TxAnalyzerWorker

Acceptance:

- Generates TxAnalyzer config.json.
- Calls CLI.
- Captures stdout/stderr.
- Imports `transactions/<tx_hash>` directory to object store.
- Writes artifact manifest and evidence row.

### C4 DecodeWorker minimal

Acceptance:

- Decodes method_selector from tx input if available.
- Decodes receipt logs if ABI available.
- Creates evidence rows for logs.

### C5 ReportWorker minimal

Acceptance:

- Generates Markdown report using template.
- Stores report artifact.

## Epic D — Forensics modules

### D1 ACLForensicsWorker

Acceptance:

- Detects RoleGranted/RoleRevoked logs.
- Creates findings for role grants.

### D2 SafeForensicsWorker

Acceptance:

- Calls getThreshold/getOwners/VERSION.
- Decodes execTransaction top-level params if ABI available.
- Supports signature type classification.

### D3 FundFlowWorker

Acceptance:

- Aggregates ERC20 Transfer logs.
- Detects ETH value transfers.
- Creates loss/fund-flow evidence.

## Epic E — Frontend

### E1 Dashboard

Acceptance:

- Lists cases.
- Filters by status/network/severity.

### E2 New Analysis

Acceptance:

- Creates case.
- Starts run.

### E3 Case Overview

Acceptance:

- Displays module status, timeline, findings, report link.

### E4 Evidence and Findings pages

Acceptance:

- Shows evidence list/detail.
- Reviewer can approve/reject finding.

## Epic F — QA and tests

### F1 Schema validation

Acceptance:

- Agent output validated by JSON schema.

### F2 Golden case fixture

Acceptance:

- Load `sample_case/megaeth_case_seed.yaml`.
- Assert required expected keys.

### F3 Integration smoke test

Acceptance:

- One EVM tx can run through create → run → artifact import → report draft.


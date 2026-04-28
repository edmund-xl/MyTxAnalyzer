# 11 MVP Roadmap and Tasks

## Phase 0 — Golden Case Prototype, 1–2 weeks

Goal: prove that the workflow can reproduce the MegaETH case structure.

| Task | Owner | Acceptance |
|---|---|---|
| Setup backend scaffold | Backend | FastAPI starts, health endpoint works |
| Setup DB schema | Backend | Alembic migration creates tables |
| Setup object store | Backend | Upload/download artifact works |
| Setup TxAnalyzer dependency | Backend | Worker can run one tx |
| Implement environment check | Backend | Returns rpc/explorer/trace capability |
| Implement transaction discovery | Backend | For seed tx/address, stores tx rows |
| Implement artifact import | Backend | TxAnalyzer directory imported to object store |
| Implement basic report markdown | Backend | Generates report from static template |

## Phase 1 — Internal MVP, 4–6 weeks

| Epic | Tasks |
|---|---|
| Case UI | dashboard, new analysis, overview |
| Timeline UI | transaction table, phase labels, evidence drawer |
| Evidence UI | evidence list/detail/raw artifact link |
| Findings UI | approve/reject/comment |
| Report UI | markdown preview and export |
| Decode Engine | top-level input decode, log decode |
| ACL Worker | RoleGranted/RoleRevoked/historical eth_call |
| Safe Worker | Safe config, execTransaction, signatures, multiSend |
| Fund Flow | ETH/ERC20 transfer aggregation, borrow/swap/bridge basics |
| RCA Agent | structured JSON output, schema validation |

## Phase 2 — Quality Upgrade, 6–10 weeks

| Epic | Tasks |
|---|---|
| Foundry Replay | exploit replay for code bug cases |
| Protocol modules | Aave/Compound/Uniswap/Curve modules |
| Cross-chain tracking | Across/Relay/LiFi/Stargate destinations |
| Graphs | React Flow multi-sig and fund flow graphs |
| Evaluation harness | historical attacks + benign tests |
| PDF export | publish-ready PDFs |

## Codex task order

1. Implement backend skeleton from `starter/backend`.
2. Implement SQLAlchemy models matching `db/schema.sql`.
3. Implement API routes matching `api/openapi.yaml`.
4. Implement object store abstraction.
5. Implement Network config loader.
6. Implement EnvironmentCheckWorker.
7. Implement TxAnalyzerWorker.
8. Implement TxDiscoveryWorker.
9. Implement DecodeWorker minimal.
10. Implement EvidenceService.
11. Implement ReportWorker minimal.
12. Implement frontend dashboard/new analysis/case overview.
13. Add Safe/ACL/FundFlow workers.
14. Add QA gates.
15. Add tests.

## MVP Definition of Done

- `docker compose up` starts API, DB, Temporal, MinIO, Redis, frontend.
- User can create and run a case.
- TxAnalyzer artifacts are generated and imported.
- Evidence rows exist.
- Timeline page renders.
- Findings can be reviewed.
- Markdown report can be generated.
- Errors are visible in Job Logs.
- No secrets committed.


# 当前实现状态 / Current Implementation Status

## 中文

快照日期：2026-04-28

本文记录 RCA Workbench 当前本地实现状态。原始规格包保留在 `docs/spec/onchain_rca_workbench_spec_v1/`，作为实现基准。

### 本地端口

RCA Workbench 与 MegaETH Pentest Workbench 已明确隔离：

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| RCA frontend | `http://127.0.0.1:3100` | Next.js 工作台 UI |
| RCA backend | `http://127.0.0.1:8100/api` | FastAPI API |
| MegaETH Pentest frontend | `http://127.0.0.1:3000` | 不属于本项目 |
| MegaETH Pentest API | `http://127.0.0.1:4000` | 不属于本项目 |

### 后端已实现范围

- FastAPI API 已覆盖 networks、cases、transactions、timeline、evidence、findings review、reports、diagrams、report exports、jobs、health。
- SQLAlchemy models 已覆盖核心 RCA 实体，并新增 `diagram_specs` 和 `report_exports`。
- 已为 case list、transaction timeline、evidence、reports、jobs、diagrams、report exports 增加运行时索引。
- Case summary endpoint：
  - `GET /api/cases/summary`
  - `GET /api/cases/{case_id}/summary`
- TxAnalyzer adapter 调用真实 CLI 路径：`scripts/pull_artifacts.py --network <NET> --tx <TX>`。
- TxAnalyzer artifact 按 network + transaction hash 缓存，避免同一交易重复拉取。
- Sui 交易发现使用 Sui JSON-RPC，不走 TxAnalyzer，因为 TxAnalyzer 只适用于 EVM。
- High/Critical finding 仍强制绑定 deterministic evidence。

### 前端已实现范围

- Dashboard case list 和中文优先的 New Analysis 简化表单。
- Case detail tabs：Overview、Diagrams、Evidence、Findings、Reports、Jobs。
- Case Detail 已改为 tab 懒加载：
  - Overview 只加载 case metadata 和聚合计数。
  - Diagrams 只在打开时加载 diagrams/timeline。
  - Evidence、Findings、Reports、Jobs 只在打开对应 tab 时加载。
- Refresh 只刷新当前 tab 需要的数据，以及 case metadata/summary。
- Reports tab 支持 Markdown preview、Mermaid 渲染、PDF export status 和 PDF download。
- Findings review action 第一版只保留 approve/reject，并限制 reviewer/admin 角色使用。

### 报告与图例输出

当前报告固定生成：

- TL;DR
- 概述
- 涉事方
- 攻击时间线
- 数据流图
- 根因分析
- 财务影响
- 分析链路与方法论
- 总分析时长
- 附录

Diagram specs 已持久化，并由页面预览和 PDF 导出共用：

- `attack_flow`
- `fund_flow`
- `evidence_map`

PDF export 是 report 的派生 artifact：

- `POST /api/reports/{report_id}/exports` 请求生成 PDF。
- `GET /api/reports/{report_id}/exports` 查询导出状态。
- `GET /api/report-exports/{export_id}/download` 下载成功生成的 PDF。
- 已成功生成的同一 report PDF 会复用，不重复渲染。
- PDF 生成失败会写入 `report_exports` 和 `job_runs`，不会覆盖 canonical Markdown report。

### Case 队列

当前精选回归队列保存在 `docs/cases/defillama_cases.yaml`。

已纳入：

- Bunni V2
- Cork Protocol
- KiloEx
- GMX V1
- Balancer V2
- Scallop Lend

Scallop Lend 已走 Sui native 处理。EVM case 使用公共 RPC 做基础验证，并在可用时接入 TxAnalyzer。

### 验证命令

后端：

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench/backend
./.venv/bin/pytest -q
```

前端：

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench/frontend
pnpm exec tsc --noEmit
pnpm build
```

Smoke check：

```bash
curl -sS http://127.0.0.1:8100/api/health
curl -sS http://127.0.0.1:8100/api/cases/summary
curl -sS -I http://127.0.0.1:3100/
```

端口保护检查：

```bash
lsof -nP -iTCP:3000 -sTCP:LISTEN
lsof -nP -iTCP:4000 -sTCP:LISTEN
lsof -nP -iTCP:3100 -sTCP:LISTEN
lsof -nP -iTCP:8100 -sTCP:LISTEN
```

### 已知缺口

- 完整 Docker Compose 验证仍需要本机先安装 Docker Desktop。
- 公共 RPC 适合 smoke test，但不适合高强度 trace/debug/archive workload。
- Explorer API enrichment 依赖用户提供 API key，不能提交到仓库。
- 大数据量 UI 性能已通过 API limit 和 tab 懒加载改善；更深层的 infinite scroll/virtualized table 仍是后续任务。
- Temporal mode 已有 scaffold，本地开发目前使用 inline workflow。
- PDF 生成依赖 Playwright/Chromium；不可用时后端会记录 fallback PDF renderer warning。

## English

Snapshot date: 2026-04-28

This document records the current local implementation state of the RCA Workbench. The original source specification remains under `docs/spec/onchain_rca_workbench_spec_v1/` as the implementation baseline.

### Local Ports

The RCA Workbench is separated from the MegaETH Pentest Workbench:

| Service | URL | Notes |
| --- | --- | --- |
| RCA frontend | `http://127.0.0.1:3100` | Next.js workbench UI |
| RCA backend | `http://127.0.0.1:8100/api` | FastAPI API |
| MegaETH Pentest frontend | `http://127.0.0.1:3000` | Not owned by this project |
| MegaETH Pentest API | `http://127.0.0.1:4000` | Not owned by this project |

### Implemented Backend Scope

- FastAPI API covers networks, cases, transactions, timeline, evidence, findings review, reports, diagrams, report exports, jobs, and health.
- SQLAlchemy models cover the core RCA entities plus `diagram_specs` and `report_exports`.
- Runtime indexes exist for case lists, transaction timelines, evidence, reports, jobs, diagrams, and report exports.
- Case summary endpoints:
  - `GET /api/cases/summary`
  - `GET /api/cases/{case_id}/summary`
- The TxAnalyzer adapter invokes the real CLI path: `scripts/pull_artifacts.py --network <NET> --tx <TX>`.
- TxAnalyzer artifacts are cached by network and transaction hash to avoid repeated pulls for the same transaction.
- Sui transaction discovery uses Sui JSON-RPC and does not route through TxAnalyzer because TxAnalyzer is EVM-specific.
- High and critical findings still require deterministic evidence.

### Implemented Frontend Scope

- Dashboard case list and Chinese-first simplified New Analysis form.
- Case detail tabs: Overview, Diagrams, Evidence, Findings, Reports, Jobs.
- Case Detail now lazy-loads tab data:
  - Overview loads case metadata and aggregate counts only.
  - Diagrams loads diagrams/timeline only when opened.
  - Evidence, Findings, Reports, and Jobs load only when their tabs are opened.
- Refresh reloads only the current tab plus case metadata/summary.
- Reports tab supports Markdown preview, Mermaid rendering, PDF export status, and PDF download.
- Findings review actions are intentionally limited to approve/reject for reviewer/admin roles in the first version.

### Report And Diagram Output

Reports currently generate:

- TL;DR
- Overview
- Involved parties
- Attack timeline
- Data-flow diagrams
- Root cause analysis
- Financial impact
- Analysis methodology
- Total analysis duration
- Appendix

Diagram specs are persisted and reused by report preview and PDF export:

- `attack_flow`
- `fund_flow`
- `evidence_map`

PDF export is a derived report artifact:

- `POST /api/reports/{report_id}/exports` requests PDF generation.
- `GET /api/reports/{report_id}/exports` checks export status.
- `GET /api/report-exports/{export_id}/download` downloads successful PDF exports.
- Existing successful PDF exports for the same report are reused instead of rerendered.
- PDF generation failure is recorded in `report_exports` and `job_runs`; it does not overwrite the canonical Markdown report.

### Case Queue

The current curated regression queue is stored in `docs/cases/defillama_cases.yaml`.

Included cases:

- Bunni V2
- Cork Protocol
- KiloEx
- GMX V1
- Balancer V2
- Scallop Lend

Scallop Lend has Sui-native handling. EVM cases use public RPC for baseline verification and TxAnalyzer where available.

### Verification Commands

Backend:

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench/backend
./.venv/bin/pytest -q
```

Frontend:

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench/frontend
pnpm exec tsc --noEmit
pnpm build
```

Smoke checks:

```bash
curl -sS http://127.0.0.1:8100/api/health
curl -sS http://127.0.0.1:8100/api/cases/summary
curl -sS -I http://127.0.0.1:3100/
```

Port safety check:

```bash
lsof -nP -iTCP:3000 -sTCP:LISTEN
lsof -nP -iTCP:4000 -sTCP:LISTEN
lsof -nP -iTCP:3100 -sTCP:LISTEN
lsof -nP -iTCP:8100 -sTCP:LISTEN
```

### Known Gaps

- Full Docker Compose validation still requires installing Docker Desktop locally.
- Public RPC endpoints are suitable for smoke tests but not reliable enough for heavy trace/debug/archive workloads.
- Explorer API enrichment depends on user-provided API keys and must not be committed.
- Large-data UI performance has improved through API limits and tab lazy loading; deeper infinite scroll/virtualized tables remain future work.
- Temporal mode is scaffolded, while local development currently uses inline workflow execution.
- PDF generation depends on Playwright/Chromium availability. When unavailable, the backend records a fallback PDF renderer warning.

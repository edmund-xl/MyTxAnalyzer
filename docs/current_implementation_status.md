# 当前实现状态 / Current Implementation Status

## 中文

快照日期：2026-05-01

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
- SQLAlchemy models 已覆盖核心 RCA 实体，并新增 `diagram_specs`、`report_exports` 和 `workflow_runs`。
- 已为 case list、transaction timeline、evidence、reports、jobs、diagrams、report exports 增加运行时索引。
- Provider 解析采用自带密钥优先、公共 RPC fallback：RPC / Explorer key 来源会进入 environment capability matrix。
- EVM receipt parser 已标准化 Transfer、Approval、fund-flow edge 和 attack step；Sui 仍使用 Sui JSON-RPC 的 events/balanceChanges。
- Case create 会校验 seed 类型和值的形状：EVM `address` seed 必须是 `0x` + 40 位十六进制字符；`0x` + 64 位交易哈希会被拒绝并提示改用 `transaction` seed。
- 交易 seed 发现支持 MegaETH 这类 provider fallback：如果 `eth_getTransactionByHash` 返回空但 receipt 存在，系统会从 receipt 的 block number 拉取 full block 并按 hash 找回交易字段。
- 普通 native value transfer 不再被提升为 high-severity 攻击 finding；如果没有 calldata、事件日志、合约/trace 异常或外部事件证据，报告会生成“链上交易预分析报告”。
- Address seed 如果没有 Explorer txlist / seed transaction，会生成 evidence boundary 和“地址线索预分析报告”，不再套用攻击事件报告模板。
- Alert seed 如果只有 DefiLlama / 官方复盘 / 新闻链接且没有 seed transaction，会生成“外部事件预分析报告”；报告只记录外部事件线索和证据缺口，不输出攻击路径、根因或修复建议。
- 报告生成链路已加入 Claim Graph 和 Report QA Gate：报告先构建可追溯 claim/evidence graph，再生成 canonical Markdown/JSON，同时写入 `.claims.json` 和 `.quality.json` artifact。
- `Report.metadata` 会记录 `claim_graph_path`、`quality_result_path`、`quality_score`、blocking/warning 数、renderer family、claim 数和 report type。
- 新增报告质量 API：
  - `GET /api/reports/{report_id}/claims`
  - `GET /api/reports/{report_id}/quality`
- `POST /api/reports/{report_id}/publish` 会执行 quality gate；存在 blocking issue 或旧报告缺少 quality artifact 时返回 `422`，要求重新生成或补证。
- FundFlow worker 读取标准化 `fund_flow_edges`，资金流图按同源地址聚合并在边上标注 amount、asset、tx/evidence 和 confidence。
- Diagram spec 的 `nodes_edges.edges` 会写入 `evidence_ids`，使 Report QA Gate 能验证图例边是否绑定证据。
- LossCalculator worker 已支持稳定币直接估值；缺少价格源时只写 evidence boundary，不伪造 USD 结论。
- Case summary endpoint：
  - `GET /api/cases/summary`
  - `GET /api/cases/{case_id}/summary`
- TxAnalyzer adapter 调用真实 CLI 路径：`scripts/pull_artifacts.py --network <NET> --tx <TX>`。
- TxAnalyzer artifact 按 network + transaction hash 缓存，避免同一交易重复拉取。
- Sui 交易发现使用 Sui JSON-RPC，不走 TxAnalyzer，因为 TxAnalyzer 只适用于 EVM。
- Inline workflow 会创建 `workflow_runs` 并把 job_runs 通过 input 中的 `workflow_run_id` 关联；Temporal mode 已拆成 step activity。
- High/Critical finding 仍强制绑定 deterministic evidence。

### 前端已实现范围

- Dashboard case list 和中文优先的 New Analysis 简化表单；地址入口会识别误填的 EVM 交易哈希并提示切换到“交易哈希 / Digest”。
- Case detail tabs：Overview、Diagrams、Evidence、Findings、Reports、Jobs。
- Case Detail 已改为 tab 懒加载：
  - Overview 只加载 case metadata 和聚合计数。
  - Diagrams 只在打开时加载 diagrams/timeline。
  - Evidence、Findings、Reports、Jobs 只在打开对应 tab 时加载。
- Refresh 只刷新当前 tab 需要的数据，以及 case metadata/summary。
- Dashboard case list、Evidence、Findings、Reports、Jobs 和 Timeline 已分页加载，不再随历史数据线性扩大首屏 payload。
- Jobs tab 同时展示 workflow run 和 worker job run，便于定位一次 run 的失败位置。
- Reports tab 支持 Markdown preview、Mermaid 渲染、PDF export status 和 PDF download，并展示 quality score、blocking/warning issue、renderer family、claim count 和 Claims preview。
- Findings review action 第一版只保留 approve/reject，并限制 reviewer/admin 角色使用。

### 报告与图例输出

当前报告按 report type 生成不同结构：

- 完整攻击 RCA：Executive Summary、结论与证据等级、事件范围、阶段时间线、实体角色、攻击路径与图、根因、财务影响、修复建议、复现验证、方法论边界、附录。
- 地址线索预分析：只说明当前可确认范围、Provider/Explorer 能力边界、不能确认的内容、进入正式 RCA 的前置条件、Evidence/Job 附录。
- 外部事件预分析：只说明 DefiLlama / 外部情报记录、外部口径与本地证据边界、当前不能确认的内容、进入正式 RCA 的前置条件。
- 链上交易预分析：只说明交易基本信息、调用与资金移动、当前 evidence、不能确认的攻击结论、后续分析建议。

旧版通用章节仍作为历史报告兼容对象：

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

报告引擎已加入 attack-type renderer registry，用于把不同事件归到可复用 renderer family：

- `address_scope_boundary`
- `amm_rounding_liquidity`
- `collateral_solvency_bypass`
- `cross_contract_reentrancy`
- `oracle_price_manipulation`
- `access_control_or_forwarder`
- `reward_accounting`
- `bridge_message_verification`
- `generic_fallback`

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
- Revert Finance

Scallop Lend 已走 Sui native 处理。EVM case 使用公共 RPC 做基础验证，并在可用时接入 TxAnalyzer。

本轮新增 Revert Finance Base case：

- Case ID: `72c5044b-d329-4467-80ae-6feb2890c9b3`
- Seed tx: `0x10429eaeb479f9149854e4aeb978a35ac02d9688f6e22371712b3878c63a64ab`
- 事件日期：2026-01-30
- 主要结论：GaugeManager / V3Utils 管理路径允许带债抵押 LP NFT 被 unstake 或修改，缺少 active-debt solvency check。
- 报告版本：v5，Markdown artifact 为 `.artifacts/cases/72c5044b-d329-4467-80ae-6feb2890c9b3/reports/report_v5.md`。
- PDF export：`b1efb25d-e459-409f-85af-eae9fb84c677`，artifact 为 `.artifacts/cases/72c5044b-d329-4467-80ae-6feb2890c9b3/reports/report_v5.pdf`，Chromium 渲染成功。
- 图例修订：当 case 已有 high/critical finding 时，`diagram_specs` 不再把通用 `data_quality` finding 放入攻击图或证据图。

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

性能数据 smoke：

```bash
DATABASE_URL="sqlite+pysqlite:///./perf_rca_workbench.db" \
  ./backend/.venv/bin/python scripts/seed_performance_data.py --reset-generated
```

### 已知缺口

- 完整 Docker Compose 验证仍需要本机先安装 Docker Desktop。
- 公共 RPC 适合 smoke test，但不适合高强度 trace/debug/archive workload。
- Explorer API enrichment 依赖用户提供 API key，不能提交到仓库。
- 大数据量 UI 性能已通过 API limit、分页和 tab 懒加载改善；更深层的 virtualized table 仍是后续任务。
- Temporal mode 已拆成 step activity；完整 Docker/Temporal smoke 仍依赖 Docker Desktop。
- PDF 生成依赖 Playwright/Chromium；不可用时后端会记录 fallback PDF renderer warning。

## English

Snapshot date: 2026-05-01

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
- SQLAlchemy models cover the core RCA entities plus `diagram_specs`, `report_exports`, and `workflow_runs`.
- Runtime indexes exist for case lists, transaction timelines, evidence, reports, jobs, diagrams, and report exports.
- Provider resolution uses bring-your-own keys first and public RPC fallback. RPC / Explorer key sources are recorded in the environment capability matrix.
- The EVM receipt parser normalizes Transfer, Approval, fund-flow edges, and attack steps. Sui continues to use Sui JSON-RPC events/balanceChanges.
- Case creation validates seed type and value shape: EVM `address` seeds must be `0x` plus 40 hex characters; `0x` plus 64 hex transaction hashes are rejected with guidance to use a `transaction` seed.
- Transaction seed discovery supports provider fallback for networks such as MegaETH: when `eth_getTransactionByHash` is empty but a receipt exists, the system fetches the full block from the receipt block number and recovers transaction fields by hash.
- Plain native value transfers are no longer promoted to high-severity attack findings. Without calldata, event logs, contract/trace anomalies, or external incident evidence, the report is generated as an “on-chain transaction pre-analysis report”.
- Address seeds without Explorer txlist or a seed transaction now produce an evidence boundary and an “address lead pre-analysis report” instead of using the attack incident report template.
- Alert seeds that only contain a DefiLlama, official postmortem, or news link now generate an “external incident pre-analysis report”. The report records the external lead and evidence gaps only; it does not output attack paths, root cause, or remediation.
- Report generation now includes a Claim Graph and Report QA Gate. The report first builds a traceable claim/evidence graph, then generates canonical Markdown/JSON plus `.claims.json` and `.quality.json` artifacts.
- `Report.metadata` records `claim_graph_path`, `quality_result_path`, `quality_score`, blocking/warning counts, renderer family, claim count, and report type.
- Report quality APIs:
  - `GET /api/reports/{report_id}/claims`
  - `GET /api/reports/{report_id}/quality`
- `POST /api/reports/{report_id}/publish` runs the quality gate. Reports with blocking issues, or older reports without quality artifacts, return `422` and must be regenerated or backed by stronger evidence.
- The FundFlow worker consumes standardized `fund_flow_edges`; fund-flow diagrams aggregate by common source address and label each edge with amount, asset, tx/evidence, and confidence.
- Diagram spec `nodes_edges.edges` now stores `evidence_ids`, allowing the Report QA Gate to verify that diagram edges are evidence-bound.
- The LossCalculator worker supports direct stablecoin valuation. When a price source is missing, it records an evidence boundary instead of fabricating USD loss.
- Case summary endpoints:
  - `GET /api/cases/summary`
  - `GET /api/cases/{case_id}/summary`
- The TxAnalyzer adapter invokes the real CLI path: `scripts/pull_artifacts.py --network <NET> --tx <TX>`.
- TxAnalyzer artifacts are cached by network and transaction hash to avoid repeated pulls for the same transaction.
- Sui transaction discovery uses Sui JSON-RPC and does not route through TxAnalyzer because TxAnalyzer is EVM-specific.
- Inline workflow creates `workflow_runs` and links job_runs through `workflow_run_id` in job input. Temporal mode is now split into step activities.
- High and critical findings still require deterministic evidence.

### Implemented Frontend Scope

- Dashboard case list and Chinese-first simplified New Analysis form; the address entry detects accidental EVM transaction hashes and tells the analyst to switch to “Transaction hash / Digest”.
- Case detail tabs: Overview, Diagrams, Evidence, Findings, Reports, Jobs.
- Case Detail now lazy-loads tab data:
  - Overview loads case metadata and aggregate counts only.
  - Diagrams loads diagrams/timeline only when opened.
  - Evidence, Findings, Reports, and Jobs load only when their tabs are opened.
- Refresh reloads only the current tab plus case metadata/summary.
- Dashboard case list, Evidence, Findings, Reports, Jobs, and Timeline are paginated so first-page payload does not grow linearly with history.
- The Jobs tab shows both workflow runs and worker job runs to locate the failed step in a specific run.
- Reports tab supports Markdown preview, Mermaid rendering, PDF export status, and PDF download, and now shows quality score, blocking/warning issues, renderer family, claim count, and a Claims preview.
- Findings review actions are intentionally limited to approve/reject for reviewer/admin roles in the first version.

### Report And Diagram Output

Reports now use different structures by report type:

- Full attack RCA: Executive Summary, conclusion/evidence level, incident scope, phase timeline, entity roles, attack path and diagrams, root cause, financial impact, remediation, reproduction/verification, methodology boundary, and appendix.
- Address lead pre-analysis: confirmed scope, Provider/Explorer capability boundary, claims that cannot be confirmed yet, prerequisites for a full RCA, and Evidence/Job appendix.
- External incident pre-analysis: DefiLlama / external intelligence record, external-vs-local evidence boundary, unconfirmed conclusions, and prerequisites for a full RCA.
- On-chain transaction pre-analysis: transaction facts, call and value movement, current evidence, attack conclusions that cannot be confirmed, and next analysis steps.

The previous generic section set remains for historical report compatibility:

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

The report engine now includes an attack-type renderer registry:

- `address_scope_boundary`
- `amm_rounding_liquidity`
- `collateral_solvency_bypass`
- `cross_contract_reentrancy`
- `oracle_price_manipulation`
- `access_control_or_forwarder`
- `reward_accounting`
- `bridge_message_verification`
- `generic_fallback`

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
- Revert Finance

Scallop Lend has Sui-native handling. EVM cases use public RPC for baseline verification and TxAnalyzer where available.

New regression case added in this update:

- Case ID: `72c5044b-d329-4467-80ae-6feb2890c9b3`
- Seed tx: `0x10429eaeb479f9149854e4aeb978a35ac02d9688f6e22371712b3878c63a64ab`
- Incident date: 2026-01-30
- Main conclusion: the GaugeManager / V3Utils management path allowed a collateralized LP NFT with active debt to be unstaked or modified without an active-debt solvency check.
- Report version: v5, with Markdown artifact at `.artifacts/cases/72c5044b-d329-4467-80ae-6feb2890c9b3/reports/report_v5.md`.
- PDF export: `b1efb25d-e459-409f-85af-eae9fb84c677`, with artifact at `.artifacts/cases/72c5044b-d329-4467-80ae-6feb2890c9b3/reports/report_v5.pdf`; Chromium rendering succeeded.
- Diagram update: when a case already has a high/critical finding, `diagram_specs` no longer places the generic `data_quality` finding into the attack-flow or evidence-map diagrams.

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

Performance data smoke:

```bash
DATABASE_URL="sqlite+pysqlite:///./perf_rca_workbench.db" \
  ./backend/.venv/bin/python scripts/seed_performance_data.py --reset-generated
```

### Known Gaps

- Full Docker Compose validation still requires installing Docker Desktop locally.
- Public RPC endpoints are suitable for smoke tests but not reliable enough for heavy trace/debug/archive workloads.
- Explorer API enrichment depends on user-provided API keys and must not be committed.
- Large-data UI performance has improved through API limits, pagination, and tab lazy loading; deeper virtualized tables remain future work.
- Temporal mode is split into step activities; full Docker/Temporal smoke still depends on Docker Desktop.
- PDF generation depends on Playwright/Chromium availability. When unavailable, the backend records a fallback PDF renderer warning.

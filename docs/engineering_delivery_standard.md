# 工程交付与文档规范

## 中文

### 目标

本规范用于约束 RCA Workbench 后续所有工程更新，确保代码、测试、运行方式和文档同步交付。任何功能、性能、报告质量、接口行为、数据模型、运维方式或 case 队列发生变化时，都必须更新对应文档。

### 文档语言格式

项目自维护交付文档必须采用双语格式：

1. 中文在前。
2. 英文在后。
3. 中文和英文表达同一事实，不允许只在其中一种语言里记录关键限制或风险。
4. 原始规格包、第三方 vendor 文档、外部引用材料保持来源原貌，不强制改写。

### 每次更新必须检查的文档

- `README.md`：入口说明、端口、启动方式、验证命令发生变化时必须更新。
- `backend/README.md`：后端启动、环境变量、测试覆盖、worker 行为发生变化时必须更新。
- `docs/current_implementation_status.md`：实现状态、已知缺口、性能策略、报告/PDF/图例能力发生变化时必须更新。
- `docs/analyst_operations_guide.md`：分析师操作、seed type 语义、RPC/Explorer key、PDF 下载或排障方式变化时必须更新。
- `docs/public_rpc_sources.md`：RPC、Explorer、链配置或验证结果变化时必须更新。
- `docs/cases/defillama_cases.yaml`：新增、删除或修正安全事件 case 时必须更新。
- `docs/spec/onchain_rca_workbench_spec_v1/`：只作为原始规格基准保存，除非明确要修订规格版本。
- 报告质量相关改动必须同步记录 Claim Graph、QA Gate、publish gate、quality API、frontend Reports tab 和 artifact 结构。

### 工程交付清单

每次代码交付至少说明：

- 改了什么。
- 为什么改。
- 涉及哪些文件和模块。
- 如何验证。
- 是否影响端口、环境变量、数据库迁移、对象存储或外部依赖。
- 是否影响报告结构、PDF 导出、图例生成或 case 回归队列。
- 有哪些已知限制或后续任务。

### 验证标准

按改动范围选择验证：

- 后端代码改动：运行 `cd backend && ./.venv/bin/pytest -q`。
- 前端代码改动：运行 `cd frontend && pnpm exec tsc --noEmit`。
- 前端构建相关改动：先停止 3100 dev server，再运行 `cd frontend && pnpm build`，构建后清理 `.next` 并恢复 3100。
- API/服务改动：至少检查 `curl -sS http://127.0.0.1:8100/api/health`。
- 端口相关改动：检查 `3000/4000/3100/8100`，避免 RCA 占用 MegaETH Pentest Workbench 端口。
- 报告/PDF/图例改动：至少用一个已有 case 验证 Markdown report、diagram specs、PDF export status 和 PDF download。
- 报告质量改动：必须验证 `.claims.json`、`.quality.json`、`GET /api/reports/{report_id}/claims`、`GET /api/reports/{report_id}/quality`，以及 blocking issue 对 publish 的阻断行为。
- 性能/分页改动：至少运行后端测试，并用 `scripts/seed_performance_data.py` 的小数据 smoke 验证 seed 脚本可执行。

### 端口保护

RCA Workbench 默认只能使用：

- Frontend: `3100`
- Backend API: `8100`

MegaETH Pentest Workbench 默认保留：

- Frontend: `3000`
- API: `4000`

除非用户明确要求，不得让 RCA 服务占用 `3000/4000`。

## English

### Goal

This standard governs all future RCA Workbench engineering updates and keeps code, tests, runtime behavior, and documentation delivered together. Any change to features, performance, report quality, API behavior, data model, operations, or the case queue must include matching documentation updates.

### Documentation Language Format

Project-owned delivery documents must be bilingual:

1. Chinese first.
2. English second.
3. Both languages must describe the same facts. Critical limitations or risks must not appear in only one language.
4. Source specification packages, third-party vendor documents, and external reference material remain in their original form unless explicitly versioned or rewritten.

### Documents To Check On Every Update

- `README.md`: update when entry instructions, ports, startup flow, or verification commands change.
- `backend/README.md`: update when backend startup, environment variables, test coverage, or worker behavior changes.
- `docs/current_implementation_status.md`: update when implementation status, known gaps, performance strategy, report/PDF/diagram capabilities change.
- `docs/analyst_operations_guide.md`: update when analyst operations, seed type semantics, RPC/Explorer keys, PDF download, or troubleshooting flow changes.
- `docs/public_rpc_sources.md`: update when RPC, explorer, chain configuration, or validation results change.
- `docs/cases/defillama_cases.yaml`: update when security incident cases are added, removed, or corrected.
- `docs/spec/onchain_rca_workbench_spec_v1/`: keep as the original specification baseline unless a new specification version is explicitly requested.
- Report quality changes must document the Claim Graph, QA Gate, publish gate, quality APIs, frontend Reports tab behavior, and artifact layout.

### Engineering Delivery Checklist

Every code delivery should state:

- What changed.
- Why it changed.
- Which files and modules were affected.
- How it was verified.
- Whether ports, environment variables, database migrations, object storage, or external dependencies were affected.
- Whether report structure, PDF export, diagram generation, or the case regression queue was affected.
- Known limitations or follow-up work.

### Verification Standard

Choose verification based on the change scope:

- Backend changes: run `cd backend && ./.venv/bin/pytest -q`.
- Frontend changes: run `cd frontend && pnpm exec tsc --noEmit`.
- Frontend build changes: stop the 3100 dev server first, run `cd frontend && pnpm build`, then remove `.next` and restore the 3100 dev server.
- API/service changes: at minimum check `curl -sS http://127.0.0.1:8100/api/health`.
- Port-related changes: check `3000/4000/3100/8100` and avoid letting RCA take the MegaETH Pentest Workbench ports.
- Report/PDF/diagram changes: verify Markdown report, diagram specs, PDF export status, and PDF download with at least one existing case.
- Report quality changes: verify `.claims.json`, `.quality.json`, `GET /api/reports/{report_id}/claims`, `GET /api/reports/{report_id}/quality`, and publish blocking behavior for blocking issues.
- Performance/pagination changes: run backend tests and verify the seed script with a small smoke run of `scripts/seed_performance_data.py`.

### Port Protection

RCA Workbench should use:

- Frontend: `3100`
- Backend API: `8100`

MegaETH Pentest Workbench should keep:

- Frontend: `3000`
- API: `4000`

Do not let RCA services occupy `3000/4000` unless the user explicitly requests it.

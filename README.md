# On-chain RCA Workbench

## 中文

内部链上攻击事件 RCA 分析与报告生成工作台。

### 目录结构

- `backend/`：FastAPI、SQLAlchemy、Alembic、Temporal workflow 和 workers。
- `frontend/`：Next.js 分析/复核工作台。
- `docs/spec/onchain_rca_workbench_spec_v1/`：原始规格包，作为实现基准保留。
- `docs/engineering_delivery_standard.md`：工程交付与文档规范。
- `docs/repository_publish.md`：GitHub 仓库发布和端口/目录防误操作说明。
- `docs/current_implementation_status.md`：当前实现状态、端口、验证命令和已知缺口。
- `docs/cases/defillama_cases.yaml`：精选 DefiLlama 回归 case 队列。
- `docs/public_rpc_sources.md`：公共 RPC 默认值和验证说明。
- `vendor/txanalyzer/`：本地 TxAnalyzer checkout，容器内目标路径为 `/opt/txanalyzer`。

### 启动

```bash
cp .env.example .env
./scripts/setup_txanalyzer.sh
docker compose up --build
```

复制 `.env.example` 后，先替换 `REPLACE_ME_*` 占位符。不要把真实 `.env` 提交到仓库。

默认本地地址：

- Frontend: `http://127.0.0.1:3100`
- Backend API: `http://127.0.0.1:8100/api`

运行 MegaETH golden case 前，需要补齐 `MEGAETH_RPC_URL`、`MEGAETH_EXPLORER_API_KEY` 和完整 MegaETH seed transaction hash。
如果 TxAnalyzer CLI 需要专用 Python 解释器，可以设置 `TXANALYZER_PYTHON`；默认使用 backend 当前解释器。

当前本机实现期间没有安装 Docker Desktop，因此完整 Docker Compose 编排验证需要先安装 Docker Desktop。

### 当前本地开发约定

RCA Workbench 端口明确避开 MegaETH Pentest Workbench：

- RCA frontend: `http://127.0.0.1:3100`
- RCA backend API: `http://127.0.0.1:8100/api`
- MegaETH Pentest Workbench 保持使用 `3000/4000`。

后端回归：

```bash
cd backend
./.venv/bin/pytest -q
```

前端检查：

```bash
cd frontend
pnpm exec tsc --noEmit
pnpm build
```

### 文档交付要求

每次功能、性能、报告质量、运维方式或接口行为发生更新，都必须同步更新对应文档。
我们自己维护的交付文档必须采用双语格式：中文在前，英文在后。原始规格包和第三方 vendor 文档保持来源原貌。

## English

Internal post-incident on-chain attack analysis and report-generation workbench.

### Layout

- `backend/`: FastAPI, SQLAlchemy, Alembic, Temporal workflows, and workers.
- `frontend/`: Next.js analyst/reviewer workbench.
- `docs/spec/onchain_rca_workbench_spec_v1/`: source specification package, retained as the implementation baseline.
- `docs/engineering_delivery_standard.md`: engineering delivery and documentation standard.
- `docs/repository_publish.md`: GitHub repository publishing notes and port/path safety rules.
- `docs/current_implementation_status.md`: current implementation status, ports, verification commands, and known gaps.
- `docs/cases/defillama_cases.yaml`: curated DefiLlama regression case queue.
- `docs/public_rpc_sources.md`: public RPC defaults and validation notes.
- `vendor/txanalyzer/`: local TxAnalyzer checkout, mounted as `/opt/txanalyzer` in containers.

### Setup

```bash
cp .env.example .env
./scripts/setup_txanalyzer.sh
docker compose up --build
```

After copying `.env.example`, replace the `REPLACE_ME_*` placeholders first. Do not commit the real `.env` file.

Default local URLs:

- Frontend: `http://127.0.0.1:3100`
- Backend API: `http://127.0.0.1:8100/api`

Fill `MEGAETH_RPC_URL`, `MEGAETH_EXPLORER_API_KEY`, and a complete MegaETH seed transaction hash before running the golden case.
`TXANALYZER_PYTHON` can be set when the TxAnalyzer CLI must run under a dedicated Python interpreter; by default the backend uses its current interpreter.

Current local note: Docker Desktop was not installed during implementation, so full Docker Compose validation requires installing Docker Desktop first.

### Current Local Development

The RCA Workbench ports are intentionally kept away from the MegaETH Pentest Workbench:

- RCA frontend: `http://127.0.0.1:3100`
- RCA backend API: `http://127.0.0.1:8100/api`
- MegaETH Pentest Workbench remains on `3000/4000`.

Backend regression:

```bash
cd backend
./.venv/bin/pytest -q
```

Frontend checks:

```bash
cd frontend
pnpm exec tsc --noEmit
pnpm build
```

### Documentation Delivery Requirement

Every update to features, performance, report quality, operations, or API behavior must include corresponding documentation updates.
Project-owned delivery documents must be bilingual: Chinese first, English second. Imported source specifications and third-party vendor documents remain unchanged.

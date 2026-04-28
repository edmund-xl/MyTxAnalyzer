# 02 System Architecture

## 1. 总体架构

```text
Frontend Workbench
  ↓ REST API
FastAPI API Gateway
  ↓
Case Service ─────────────── PostgreSQL
  ↓
Temporal Workflow Engine ─── Worker Pool
  ↓                         ├─ EnvironmentCheckWorker
Artifact Store <────────────├─ TxDiscoveryWorker
  ↑                         ├─ TxAnalyzerWorker
  └─────────────────────────├─ DecodeWorker
                            ├─ ProxyResolverWorker
                            ├─ ACLForensicsWorker
                            ├─ SafeForensicsWorker
                            ├─ FundFlowWorker
                            ├─ LossCalculatorWorker
                            ├─ RCAAgentWorker
                            └─ ReportWorker
```

## 2. 组件职责

| 组件 | 职责 |
|---|---|
| Frontend | Case 创建、状态查看、timeline、trace、evidence、finding review、report export |
| API Gateway | REST API、认证、权限、请求校验 |
| Case Service | case CRUD、状态流转、metadata 管理 |
| Temporal | 编排长耗时可重试 workflow |
| Worker Pool | 执行链上取证、TxAnalyzer、decode、Agent、report |
| PostgreSQL | 结构化数据：case、tx、evidence、finding、report、job |
| S3/MinIO | 原始 artifacts：trace、source、opcode、receipt、report 文件 |
| Redis | 缓存、rate limit、短期 selector cache |
| TxAnalyzer | 核心 artifact pull 和交易级方法论能力 |
| Agent Service | 生成结构化 findings 和报告草稿，不直接越过 evidence |

## 3. 部署拓扑

```text
Docker Compose MVP
├── api               FastAPI
├── worker            Temporal worker process
├── temporal          Temporal server
├── postgres          PostgreSQL
├── minio             Artifact object store
├── redis             Cache/rate limit
├── frontend          Next.js
└── txanalyzer        mounted volume or git submodule path
```

生产部署可迁移到 Kubernetes，但 MVP 使用 Docker Compose。

## 4. 数据流

### 4.1 新建 case

1. Frontend 调用 `POST /api/cases`。
2. API 写入 `cases`。
3. 用户调用 `POST /api/cases/{case_id}/run`。
4. API 启动 Temporal workflow。

### 4.2 分析 workflow

```text
CaseCreated
  → EnvironmentCheck
  → TxDiscovery
  → ArtifactPull(TxAnalyzer)
  → Decode
  → EvidenceBuild
  → ModuleForensics
  → RCAAgent
  → ReportDraft
  → Review
```

### 4.3 Artifact 存储

对象存储路径统一为：

```text
s3://<bucket>/cases/<case_id>/transactions/<tx_hash>/<producer>/<file>
```

示例：

```text
s3://rca-artifacts/cases/case_001/transactions/0xb96c.../txanalyzer/trace/call_trace.json
s3://rca-artifacts/cases/case_001/transactions/0xb96c.../txanalyzer/contracts/0x4c24.../source.sol
s3://rca-artifacts/cases/case_001/reports/report_v1.md
```

## 5. Agent 架构

Agent 不能直接从 raw trace 输出最终报告。必须按以下管道：

```text
Raw Artifacts
  → Deterministic Decoding
  → Structured Evidence
  → Module Findings
  → RCA Agent JSON Output
  → QA Gate
  → Report Writer
  → Human Review
```

## 6. 可扩展性

| 扩展点 | 方式 |
|---|---|
| 新链 | 新增 network config + chain adapter capability |
| 新协议 | 新增 protocol module worker |
| 新 bridge | 新增 bridge decoder |
| 新报告模板 | 新增 report template |
| 新模型 | 替换 Agent Service adapter |
| 新 artifact source | 增加 evidence producer |

## 7. 失败与降级

| 失败项 | 降级策略 |
|---|---|
| RPC 不支持 debug_trace | 标记 `debug_trace_ok=false`，禁用 opcode/ecrecover debug cross-check |
| Explorer 无源码 | 使用 ABI/selector/decompile，source confidence 降级 |
| TxAnalyzer 单笔失败 | case 不整体失败；该 tx 标记 artifact_failed |
| Agent 输出 JSON 不合法 | 重试一次；仍失败则保存 raw output 并标记 agent_failed |
| 跨链目标查询失败 | fund flow 标记 partial，不输出 High-confidence destination finding |

## 8. 安全要求

- API key 只能存在 env/secret manager。
- artifact store 默认私有。
- 所有 case 访问需要 RBAC。
- 高风险归因发布需要 reviewer approval。
- 保存所有外部 API response hash，便于复核。
- Prompt 和 model version 必须记录。


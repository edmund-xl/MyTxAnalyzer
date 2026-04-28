# On-chain RCA Workbench — 事后链上攻击分析与报告生成系统设计包 v1.0

本设计包面向 Codex/工程实现人员，目标是把“TxAnalyzer + 链上取证 + Agent 报告生成”的人工流程产品化，做成内部同事可使用的事后攻击分析报告系统。

## 目标

输入一个 seed transaction、attacker address、protocol contract 或人工告警，系统自动完成：

1. 网络环境检查；
2. 相关交易发现与聚类；
3. 调用 TxAnalyzer 批量拉取 artifacts；
4. ABI / selector / event / trace 解码；
5. 权限、Gnosis Safe、多签、资金流、损失测算等取证模块；
6. 结构化 evidence 和 findings；
7. Agent 生成 RCA 报告草稿；
8. 分析师审核；
9. 导出 Markdown / PDF / HTML 报告。

## 第一阶段边界

本系统不是实时监控系统，不做 mempool，不做全链告警，不做无人审核自动发布。

第一阶段只做：

- EVM 事后分析；
- seed tx / address 输入；
- 报告质量对齐 MegaETH Aave V3 样本；
- 人工审核后发布；
- TxAnalyzer 作为核心 artifact/RCA 能力入口。

## 推荐阅读顺序

Codex 或工程师应按以下顺序阅读：

1. `CODEx_START_HERE.md`
2. `docs/01_PRD.md`
3. `docs/02_SYSTEM_ARCHITECTURE.md`
4. `docs/04_WORKFLOW_AND_STATE_MACHINE.md`
5. `docs/06_WORKER_MODULE_SPECS.md`
6. `docs/07_TXANALYZER_INTEGRATION.md`
7. `api/openapi.yaml`
8. `db/schema.sql`
9. `schemas/*.json`
10. `tickets/MVP_CODING_TASKS.md`

## 核心约束

- 所有关键结论必须绑定 evidence。
- 没有链上证据的内容不能作为 High-confidence finding。
- 多签签名结论必须由 Safe decode / ecrecover / approvedHash / debug trace 中至少一种支持。
- 权限类结论必须由 RoleGranted/RoleRevoked logs、historical eth_call、trace 或源码路径支持。
- 资金损失金额必须来自 Transfer logs、Borrow events、balance diff 或 bridge events。
- Agent 只能生成结构化 findings 和报告草稿，不能绕过 Evidence Store。

## 是否用到 TxAnalyzer

是。TxAnalyzer 是本系统 P0 级核心依赖，用于批量拉取 EVM 交易 artifacts，包括 trace、contract source、opcode、selector mapping，并作为 6-phase attack transaction methodology 的基础。系统通过 `TxAnalyzerWorker` 调用 TxAnalyzer CLI，并把 `transactions/<tx_hash>/` 下的 artifacts 导入 Evidence Store。


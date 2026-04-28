# 01 PRD — 事后链上攻击分析与报告生成工作台

## 1. 产品定位

产品名称：On-chain RCA Workbench。

定位：用于内部安全团队的事后攻击分析与报告生成系统。

核心目标：把分析师手动执行的链上取证流程标准化、产品化，让同事可以通过 Web UI 输入交易或地址，获得接近专业安全事件报告质量的 RCA 报告草稿。

## 2. 非目标

本阶段不做：

- 实时攻击检测；
- mempool 监控；
- 自动告警；
- 自动对外发布；
- 所有链所有协议覆盖；
- 无人审核归因；
- Solana 深度 replay。

## 3. 用户角色

| 角色 | 需求 | 权限 |
|---|---|---|
| Analyst | 新建 case、查看 trace、审核 evidence、生成报告 | 创建、运行、审核、导出 |
| Reviewer | 审核高风险 finding 和最终报告 | 审核、退回、发布 |
| Admin | 配置网络、API key、模型、模块开关 | 全部权限 |
| Reader | 查看已发布报告和历史案例 | 只读 |

## 4. 核心用户故事

### US-001 新建分析

作为 Analyst，我可以输入 network 和 seed tx，创建一个 case，并选择 Quick 或 Full 分析深度。

验收：

- 创建后返回 case_id。
- case 状态为 `CREATED`。
- 系统保存 seed_type、seed_value、network、time_window、depth。

### US-002 环境检查

作为 Analyst，我需要知道当前链的 RPC 和 Explorer 是否足以支持报告级分析。

验收：

- 显示 chain_id、rpc_ok、trace_ok、debug_trace_ok、explorer_ok、historical_call_ok。
- 如果 debug_trace 不可用，系统显示降级影响。

### US-003 相关交易发现

作为 Analyst，我希望系统从 seed tx/address 扩展出攻击交易、授权交易、补救交易和资金流交易。

验收：

- 生成 related_transactions 列表。
- 每笔交易包含 tx_hash、timestamp、block_number、from、to、method、phase_guess。
- 支持人工把交易加入/移出 case。

### US-004 TxAnalyzer artifacts 拉取

作为 Analyst，我希望系统为每笔相关交易拉取 trace、source、opcode、selector 等 artifacts。

验收：

- 每笔交易创建 artifact_manifest。
- artifact 存在对象存储路径。
- TxAnalyzer 调用失败时记录错误和降级状态。

### US-005 Evidence 和 Finding

作为 Reviewer，我希望每个结论都能点击查看证据。

验收：

- finding 包含 evidence_ids。
- evidence 包含 raw_path、decoded、confidence。
- 没有 evidence 的 finding 不能标记为 High。

### US-006 报告生成

作为 Analyst，我希望系统生成对齐样本质量的中文报告草稿。

验收：

- 报告包括 TL;DR、概述、涉事方、时间线、根因、多签/权限、资金流、财务影响、补救、方法论、数据可靠性、附录。
- 报告每个关键段落有 evidence coverage。
- 报告状态为 `DRAFT`，不能自动发布。

### US-007 审核发布

作为 Reviewer，我可以批准或拒绝 finding，并最终发布报告。

验收：

- 高风险 finding 必须 reviewer approval。
- 发布报告保存版本号和 reviewer。
- 被拒绝 finding 不进入最终报告。

## 5. MVP 功能范围

### P0 必须实现

| 模块 | 功能 |
|---|---|
| Case Management | 新建、列表、状态、详情 |
| Network Config | 网络配置、RPC/Explorer 能力 |
| Environment Check | RPC、trace、debug trace、Explorer 检查 |
| Tx Discovery | seed tx/address 扩展交易列表 |
| TxAnalyzer Adapter | 调用 TxAnalyzer，导入 artifacts |
| Decode Engine | top-level ABI/selector/event decode |
| Evidence Store | 结构化证据对象 |
| Timeline Builder | Phase timeline |
| Findings Engine | 模块输出 + Agent 输出 findings |
| Report Builder | Markdown 报告草稿 |
| Review Workflow | approve/reject/comment |

### P1

| 模块 | 功能 |
|---|---|
| Safe Forensics | Gnosis Safe signer recovery |
| ACL Forensics | AccessControl/Ownable 权限链 |
| Fund Flow | ETH/ERC20/DEX/Bridge 资金流 |
| Source Audit | 源码路径 + validation gates |
| PDF Export | 报告 PDF |
| React Flow Graphs | 多签图、资金流图 |

### P2

| 模块 | 功能 |
|---|---|
| Foundry Replay | 代码漏洞型 replay |
| Cross-chain Tracker | 跨链到账和后续流向 |
| Protocol Modules | Aave、Compound、Uniswap、Curve、Stargate 等 |
| Evaluation Harness | 历史攻击/正常交易回归测试 |

## 6. 报告质量标准

报告质量不是看文字长度，而是看证据闭环。

| 维度 | 通过标准 |
|---|---|
| 时间线 | 攻击前置、执行、资金转移、补救能串起来 |
| 根因 | 能解释攻击者为何有能力改变账本或转走资产 |
| 证据 | 每个关键结论有 tx/log/trace/source/state/signature 中至少一类证据 |
| 金额 | 损失金额来自 Transfer/Borrow/balance diff/bridge event |
| 权限 | 权限类结论有 RoleGranted/eth_call/trace/source 支持 |
| 多签 | signer 结论有 Safe decode/ecrecover/approvedHash 支持 |
| 置信度 | 无法验证部分标记 Partial/Low |
| 可复现 | 保存 artifacts、prompt、model、report version |

## 7. 成功指标

| 指标 | 目标 |
|---|---|
| 首版研判耗时 | 单 case 10 分钟内生成 Quick Assessment |
| 完整报告耗时 | 30–90 分钟内生成可审核 Full Report |
| Evidence coverage | High findings 100% 有 evidence |
| 复现率 | MegaETH golden case 核心结论可复现 |
| Reviewer 修改率 | 发布报告中关键事实修改率逐步下降 |


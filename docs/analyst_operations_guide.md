# 分析师操作手册 / Analyst Operations Guide

## 中文

### 1. 创建 Case

打开 `http://127.0.0.1:3100`，在 Dashboard 的“新建分析”区域填写：

- `网络`：选择实际发生事件的链。
- `入口类型`：优先选择“交易哈希 / Digest”。没有交易时可先用“地址”或“外部事件链接”建案。
- `入口值`：填写交易 hash、Sui digest、地址或公开事件链接。
- `标题`：可选。留空时系统按 seed 自动生成。

如果输入值是 `0x` + 64 位十六进制字符，它是 EVM 交易哈希，不是地址。Dashboard 和后端会拒绝把这类值作为 `地址` seed 创建 case，应切换到“交易哈希 / Digest”。

创建后进入 case 详情页，点击 `Run Analysis` 启动 inline workflow。开发环境默认使用 `WORKFLOW_MODE=inline`，不会占用 `3000/4000`。

### 2. 如何选择入口类型

- `交易哈希 / Digest`：证据质量最高。EVM 会拉取 transaction、receipt、logs，并尝试 TxAnalyzer artifact；Sui 会调用 Sui JSON-RPC。
- `地址`：适合只有攻击者或合约地址时使用。EVM 地址必须是 `0x` + 40 位十六进制字符；EVM 地址扩展依赖 Explorer API key，没有 key 时系统只记录降级 evidence boundary，不伪造交易。
- `外部事件链接`：适合只有 DefiLlama、官方复盘或新闻链接时先建案。系统会记录 external alert evidence，等待后续补 seed transaction。

MegaETH 公共 RPC 可能出现 `eth_getTransactionByHash` 返回空、但 receipt 正常存在的情况。系统会自动用 receipt 的 block number 拉取 full block，再按 hash 找回交易字段；如果 full block 也不可用，报告会写成 provider evidence boundary。

单笔 native value transfer 只证明资金移动，不自动等同于攻击、损失或漏洞根因。没有 calldata、事件日志、合约/trace 异常或外部事件证据时，报告会写成“链上交易预分析报告”。

### 3. 配置 RPC / Explorer Key

密钥只放在 `.env` 或运行环境变量里，不能入库、不能提交。

常用变量：

```bash
ETH_RPC_URL=...
BASE_RPC_URL=...
BSC_RPC_URL=...
ARBITRUM_RPC_URL=...
SUI_RPC_URL=...
ETHERSCAN_API_KEY=...
ETH_EXPLORER_API_KEY=...
BASE_EXPLORER_API_KEY=...
BSC_EXPLORER_API_KEY=...
ARBITRUM_EXPLORER_API_KEY=...
```

系统解析顺序是：网络专用 env var 优先，通用 `ETHERSCAN_API_KEY` 其次，公共 RPC fallback 最后。公共 RPC 只适合 smoke test 和基础 receipt，不保证 trace/debug/archive 能力。

### 4. 判断 Evidence 是否足够

High/Critical finding 必须绑定 deterministic evidence。当前 deterministic evidence 包括：

- `receipt_log`
- `trace_call`
- `source_line`
- `state_call`
- `signature`
- `balance_diff`
- `tx_metadata`

如果只存在公开文章、新闻或 provider degradation evidence，报告只能写“证据边界”，不能写成确定性攻击结论。

### 4.1 地址线索报告的边界

当入口类型是 `地址` 且系统没有拿到 txlist/receipt/trace 时，报告会生成“地址线索预分析报告”，而不是“攻击事件分析报告”。该报告只说明：

- 地址已被记录为线索。
- RPC / Explorer 能力检查结果。
- 为什么当前不能确认攻击者、受害协议、根因或损失。
- 进入正式 RCA 所需的确定条件：seed transaction 或 Explorer txlist。

这类报告不应出现“铸造虚假抵押品”“借出真实资产”“跨链转出”等攻击段落，除非已有 deterministic transfer / receipt / trace evidence。

### 4.2 报告质量面板

生成报告后，`Reports` tab 会同时显示：

- `Quality Score`：从 100 开始，blocking issue 每项扣 30，warning 每项扣 5。
- `Blocking` / `Warnings`：发布前必须处理 blocking issue；warning 可作为补证或改写优先级。
- `Renderer` / `Report Type`：确认报告是否使用了正确的 attack family 或预分析降级结构。
- `Claims Preview`：只读展示报告的核心 claim、claim type、confidence 和 evidence 数量。

如果质量面板显示旧报告缺少 quality artifact，应重新点击 `Draft Report` 生成新版。`Publish` 会执行 QA Gate；High/Critical finding 缺 deterministic evidence、完整 RCA 缺交易范围、root cause claim 无 evidence、普通 native transfer 被写成攻击等问题会被阻断。

### 5. Approve / Reject Finding

在 case 详情页打开 `Findings`：

- `Approve`：表示 reviewer 接受该 finding，可进入最终发布报告。
- `Reject`：表示该 finding 不进入最终报告。

pending 或 rejected finding 不应作为 published 报告的确定性结论。

### 6. 生成和下载 PDF

在 `Reports` tab：

1. 点击 `Draft Report` 生成 Markdown canonical report。
2. 点击 `Export PDF` 生成派生 PDF artifact。
3. 等待状态变成 `success`。
4. 点击 `Download PDF`。

PDF 与页面预览共用同一份 report content 和 `diagram_specs`，避免图例分叉。

### 7. 排障

- TxAnalyzer 失败：查看 `Jobs` tab 的 `txanalyzer_worker`，确认 `/opt/txanalyzer/scripts/pull_artifacts.py` 或 `vendor/txanalyzer` 是否存在。
- RPC 降级：查看 `environment_capability` evidence，确认 `eth_chainId`、receipt、trace/debug、Explorer 能力矩阵。
- Temporal 未跑：本地默认 inline；Docker/生产才使用 Temporal。没有 Docker Desktop 时只做代码和单元测试验证。
- PDF 失败：查看 `report_exports.error` 和 `Jobs` tab；本地需要 Playwright/Chromium。
- Mermaid 不显示：确认 report 中存在 fenced `mermaid` block，并刷新当前 `Reports` tab。

### 8. 性能回归数据

本地生成大数据量 smoke：

```bash
DATABASE_URL="sqlite+pysqlite:///./perf_rca_workbench.db" \
  ./backend/.venv/bin/python scripts/seed_performance_data.py --reset-generated
```

默认会生成 5,000 cases、100,000 evidence、20,000 job_runs、5,000 reports、15,000 diagrams 和 5,000 PDF export rows。Dashboard 和 case detail tab 应继续通过分页加载。

## English

### 1. Create A Case

Open `http://127.0.0.1:3100` and use the Dashboard “New Analysis” form:

- `Network`: choose the chain where the incident happened.
- `Entry type`: prefer “Transaction hash / Digest”. Use “Address” or “External incident link” when no transaction is available yet.
- `Entry value`: enter a transaction hash, Sui digest, address, or public incident link.
- `Title`: optional. If omitted, the system generates one from the seed.

If the value is `0x` plus 64 hex characters, it is an EVM transaction hash, not an address. The Dashboard and backend reject that value as an `Address` seed; switch the entry type to “Transaction hash / Digest”.

After creation, open the case detail page and click `Run Analysis` to start the inline workflow. Local development defaults to `WORKFLOW_MODE=inline` and does not use ports `3000/4000`.

### 2. Choose The Seed Type

- `Transaction hash / Digest`: highest evidence quality. EVM pulls transaction, receipt, logs, and TxAnalyzer artifacts where possible; Sui uses Sui JSON-RPC.
- `Address`: useful when only an attacker or contract address is known. EVM addresses must be `0x` plus 40 hex characters. EVM address expansion requires an Explorer API key; without a key the system records a degradation evidence boundary and does not fabricate transactions.
- `External incident link`: useful when only DefiLlama, an official postmortem, or a news link is available. The system records external alert evidence and waits for a later seed transaction.

MegaETH public RPC may return an empty `eth_getTransactionByHash` response while the receipt is available. The system automatically uses the receipt block number to fetch the full block and recover transaction fields by hash; if the full block is also unavailable, the report must stay within a provider evidence boundary.

A single native value transfer proves asset movement only. It is not automatically treated as an exploit, loss, or root cause. Without calldata, event logs, contract/trace anomalies, or external incident evidence, the report is generated as an “on-chain transaction pre-analysis report”.

### 3. Configure RPC / Explorer Keys

Secrets must live only in `.env` or runtime environment variables. They must not be stored in the database or committed.

Common variables:

```bash
ETH_RPC_URL=...
BASE_RPC_URL=...
BSC_RPC_URL=...
ARBITRUM_RPC_URL=...
SUI_RPC_URL=...
ETHERSCAN_API_KEY=...
ETH_EXPLORER_API_KEY=...
BASE_EXPLORER_API_KEY=...
BSC_EXPLORER_API_KEY=...
ARBITRUM_EXPLORER_API_KEY=...
```

Resolution order is network-specific env var first, generic `ETHERSCAN_API_KEY` second, and public RPC fallback last. Public RPC is suitable for smoke tests and baseline receipts only; trace/debug/archive support is not guaranteed.

### 4. Decide Whether Evidence Is Sufficient

High/Critical findings must bind deterministic evidence. Current deterministic evidence types are:

- `receipt_log`
- `trace_call`
- `source_line`
- `state_call`
- `signature`
- `balance_diff`
- `tx_metadata`

If only public articles, news, or provider degradation evidence exists, the report must describe evidence boundaries instead of deterministic conclusions.

### 4.1 Boundary For Address-Seed Reports

When the entry type is `Address` and the system has no txlist, receipt, or trace data, the report is generated as an “address lead pre-analysis report”, not an “attack incident RCA report”. It only states:

- The address has been recorded as a lead.
- RPC / Explorer capability results.
- Why attacker, victim protocol, root cause, and loss cannot be confirmed yet.
- The deterministic condition required for formal RCA: a seed transaction or Explorer txlist.

These reports should not include attack-stage sections such as “fake collateral mint”, “real asset borrow”, or “bridge outflow” unless deterministic transfer / receipt / trace evidence exists.

### 4.2 Report Quality Panel

After generating a report, the `Reports` tab shows:

- `Quality Score`: starts at 100; each blocking issue subtracts 30 and each warning subtracts 5.
- `Blocking` / `Warnings`: blocking issues must be resolved before publish; warnings guide evidence collection or wording improvements.
- `Renderer` / `Report Type`: confirms whether the report used the correct attack family or a pre-analysis downgrade structure.
- `Claims Preview`: read-only view of core claims, claim type, confidence, and evidence count.

If the quality panel says an older report has no quality artifact, click `Draft Report` again to generate a new version. `Publish` runs the QA Gate; missing deterministic evidence for High/Critical findings, full RCA without transaction scope, root-cause claims without evidence, or plain native transfers written as attacks are blocked.

### 5. Approve / Reject Findings

Open the `Findings` tab on the case detail page:

- `Approve`: the reviewer accepts the finding and it may enter the final published report.
- `Reject`: the finding must not enter the final report.

Pending or rejected findings should not be used as deterministic conclusions in a published report.

### 6. Generate And Download PDF

In the `Reports` tab:

1. Click `Draft Report` to generate the canonical Markdown report.
2. Click `Export PDF` to generate the derived PDF artifact.
3. Wait until the status becomes `success`.
4. Click `Download PDF`.

PDF export and page preview reuse the same report content and `diagram_specs`, so diagrams stay consistent.

### 7. Troubleshooting

- TxAnalyzer failure: check `txanalyzer_worker` in the `Jobs` tab and confirm `/opt/txanalyzer/scripts/pull_artifacts.py` or `vendor/txanalyzer` exists.
- RPC degradation: inspect `environment_capability` evidence for `eth_chainId`, receipt, trace/debug, and Explorer capability matrix.
- Temporal not running: local development defaults to inline mode; Docker/production uses Temporal. Without Docker Desktop, validate code and unit tests only.
- PDF failure: check `report_exports.error` and the `Jobs` tab; local rendering needs Playwright/Chromium.
- Mermaid missing: confirm the report contains fenced `mermaid` blocks and refresh the current `Reports` tab.

### 8. Performance Regression Data

Generate local large-data smoke rows:

```bash
DATABASE_URL="sqlite+pysqlite:///./perf_rca_workbench.db" \
  ./backend/.venv/bin/python scripts/seed_performance_data.py --reset-generated
```

The default seed creates 5,000 cases, 100,000 evidence rows, 20,000 job_runs, 5,000 reports, 15,000 diagrams, and 5,000 PDF export rows. Dashboard and case detail tabs should continue to load through pagination.

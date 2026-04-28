# 03 UI / UX Specification

## 1. 信息架构

```text
Dashboard
├── New Analysis
├── Case Overview
│   ├── Timeline
│   ├── Transactions
│   ├── Trace Explorer
│   ├── Source Audit
│   ├── Evidence
│   ├── Findings
│   ├── Multisig Forensics
│   ├── ACL / Permission
│   ├── Fund Flow
│   ├── Reports
│   └── Job Logs
├── Case Library
├── Network Config
└── Admin
```

## 2. Dashboard

### 2.1 目标

让分析师快速查看所有 case 的状态、严重性和审核队列。

### 2.2 表格字段

| 字段 | 类型 | 示例 |
|---|---|---|
| Case ID | link | CASE-2026-0007 |
| Title | string | MegaETH Aave V3 Incident |
| Network | badge | megaeth |
| Status | badge | REPORT_DRAFTED |
| Severity | badge | CRITICAL |
| Seed | string | tx: 0xb96c... |
| Attack Type | badge | Access Control Abuse |
| Loss Estimate | currency | $305,000 |
| Confidence | badge | High |
| Owner | user | analyst-a |
| Updated | datetime | 2026-04-25 16:00 |

### 2.3 操作

- Create New Analysis
- Filter by status/severity/network/owner
- Open case
- Re-run failed job

## 3. New Analysis 页面

### 3.1 输入字段

| 字段 | 控件 | 必填 | 默认 |
|---|---|---:|---|
| Network | select | 是 | eth |
| Seed Type | segmented control | 是 | transaction |
| Seed Value | input | 是 | empty |
| Time Window Hours | number | 否 | 6 |
| Depth | select | 是 | quick |
| Modules | checkbox group | 否 | auto |
| Output Language | select | 是 | zh-CN |
| Report Template | select | 是 | incident_rca |

### 3.2 Depth 定义

| Depth | 行为 |
|---|---|
| quick | environment + discovery + TxAnalyzer artifacts + basic decode + timeline + quick findings |
| full | quick + ACL + Safe + fund flow + loss + report |
| full_replay | full + Foundry replay when applicable，P1 |

### 3.3 提交后行为

- 创建 case。
- 页面跳转 Case Overview。
- 自动启动 workflow，或显示 Run 按钮。

## 4. Case Overview

### 4.1 顶部摘要卡

显示：

- Case title
- Network
- Status
- Severity
- Attack type
- Root cause one-liner
- Loss estimate
- Confidence
- Owner
- Last run

### 4.2 模块状态卡

| 模块 | 状态 | 说明 |
|---|---|---|
| Environment | Done/Failed/Partial | RPC/Explorer 能力 |
| Discovery | Done | 相关交易数量 |
| TxAnalyzer | Running/Done/Failed | artifacts 数量 |
| Decode | Done | decoded calls/events |
| ACL | Done/Partial/Skipped | role grant/revoke |
| Safe | Done/Partial/Skipped | signer recovery |
| Fund Flow | Done/Partial | source/destination |
| Report | Drafted/Review/Published | 报告状态 |

### 4.3 右侧风险提示

- Missing trace
- Missing source
- Missing reviewer
- Low-confidence claims
- Cross-chain incomplete

## 5. Timeline 页面

### 5.1 表格

| Time | Phase | Tx | From | To | Method | Amount | Evidence | Confidence |
|---|---|---|---|---|---|---|---|---|

### 5.2 Phase 颜色

- Privilege / ACL: red
- Asset Extraction: orange
- Swap / Bridge: purple
- Remediation: green
- Unknown: gray

### 5.3 点击行为

点击 tx 或 phase 后，右侧 drawer 显示：

- tx metadata
- decoded input
- trace snippet
- related logs
- evidence list
- source path
- findings using this tx

## 6. Trace Explorer

### 6.1 布局

```text
左：Call Tree
中：Decoded Call / Parameters
右：Source Viewer
下：Logs / Storage Writes / Balance Diff / Raw JSON
```

### 6.2 功能

- search by address/function/selector
- expand delegatecall
- show proxy implementation
- pin call as evidence
- copy JSON path
- open source line if available

## 7. Evidence 页面

### 7.1 列表字段

| 字段 | 说明 |
|---|---|
| Evidence ID | ev_... |
| Type | receipt_log / trace_call / source_line / state_call / signature / balance_diff |
| Producer | decode_worker / safe_worker / acl_worker / txanalyzer_worker |
| Claim Supported | claim key |
| Confidence | high/medium/low |
| Raw Path | artifact path |
| Created | timestamp |

### 7.2 Evidence detail

- decoded JSON
- raw artifact link
- source module
- related findings
- reviewer notes

## 8. Findings 页面

### 8.1 列表字段

| 字段 | 说明 |
|---|---|
| Title | finding 标题 |
| Type | AccessControl / FundFlow / ContractBug / Multisig / Loss |
| Severity | Critical/High/Medium/Low/Info |
| Confidence | High/Medium/Low/Partial |
| Evidence Count | number |
| Reviewer Status | Pending/Approved/Rejected |

### 8.2 审核操作

- Approve
- Reject
- Request More Evidence
- Add Comment
- Downgrade Confidence

## 9. Multisig Forensics 页面

### 9.1 展示内容

- Safe address
- Safe version
- threshold
- owners
- attack tx submitter
- recovered signers
- signature types
- internal MultiSend actions
- remediation signer matrix

### 9.2 图表

使用 React Flow：

```text
Owner 1 ──ECDSA──▶ Safe ──grantRole x5──▶ Attacker
Owner 2 ──submit/approvedHash──▶ Safe
Owner 3 ──remediation only──▶ Safe
```

## 10. Fund Flow 页面

### 10.1 图表节点

- Borrow event
- ERC20 transfer
- DEX swap
- Bridge deposit
- Destination chain receipt
- CEX/Mixer label if available

### 10.2 表格字段

| Time | Tx | Asset | Amount In | Amount Out | From | To | Protocol | Evidence |
|---|---|---:|---:|---|---|---|---|

## 11. Report Builder

### 11.1 报告区块

- TL;DR
- Overview
- Parties
- Attack Timeline
- Root Cause
- Multisig / Permission Forensics
- Fund Flow
- Financial Impact
- Remediation
- Data Reliability
- Methodology
- Appendix

### 11.2 区块状态

| 状态 | 含义 |
|---|---|
| Green | evidence coverage complete |
| Yellow | partial evidence |
| Red | unsupported claim |
| Grey | background only |

### 11.3 导出

- Markdown P0
- PDF P1
- HTML P1
- JSON P0


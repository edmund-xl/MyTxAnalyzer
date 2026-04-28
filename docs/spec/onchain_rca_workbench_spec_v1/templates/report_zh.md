# {{ case.title }} 攻击事件分析报告

## TL;DR

> **事件类型:** {{ case.attack_type }}
> **链:** {{ network.name }} (Chain ID: {{ network.chain_id }})
> **日期:** {{ incident_date }}
> **攻击窗口:** {{ attack_window }}
> **损失:** {{ loss_summary }}
> **分析工具:** TxAnalyzer + trace/debug RPC + Explorer API + 链上取证
> **置信度:** {{ confidence }}

## 1. 概述

{{ overview }}

## 2. 涉事方

### 2.1 Gnosis Safe 多签钱包 / 核心权限主体

{{ victim_or_protocol_table }}

### 2.2 攻击者地址

{{ attacker_table }}

### 2.3 已采集证据来源

{{ evidence_source_table }}

## 3. 攻击时间线

{{ timeline_table }}

### 关键交易分析

{{ key_transactions }}

## 4. 根因分析

### 4.1 合约代码没有问题

{{ contract_code_assessment }}

{{ findings_table }}

### 4.2 根因：{{ root_cause_label }}

{{ root_cause_chain }}

### 4.3 可能的攻击者身份推断

{{ attacker_identity_hypothesis }}

### 4.4 证据边界

{{ evidence_boundary }}

## 5. 财务影响

### 5.1 铸造虚假抵押品

{{ fake_collateral_impact }}

### 5.2 借出的真实资产

{{ borrowed_assets_table }}

### 5.3 跨链转出

{{ bridge_out_impact }}

### 5.4 总损失

{{ total_loss_table }}

### 5.5 攻击成本

{{ attack_cost }}

### 5.6 资金流证据

{{ fund_flow_evidence }}

## 6. 分析链路与方法论

### 6.1 分析工具栈

{{ tool_stack_table }}

### 6.2 分析步骤

{{ methodology }}

### 6.3 关键查询清单

{{ query_checklist_table }}

### 6.4 数据可靠性

{{ data_reliability }}

## 7. 总分析时长

{{ analysis_duration }}

## 附录

### A.1 交易列表

{{ transaction_appendix }}

### A.2 Evidence 列表

{{ evidence_appendix }}

### A.3 Worker 执行记录

{{ worker_runs_table }}

### A.4 未解决问题

{{ open_questions }}

# 05 Data Model

## 1. 实体关系

```text
Network 1 ── * Case
Case 1 ── * Transaction
Case 1 ── * Address
Case 1 ── * Contract
Case 1 ── * Artifact
Case 1 ── * Evidence
Case 1 ── * Finding
Finding * ── * Evidence
Case 1 ── * Report
Case 1 ── * JobRun
```

## 2. Case

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | case id |
| title | text | 自动或人工标题 |
| network_key | text | e.g. eth, bsc, megaeth |
| seed_type | enum | transaction/address/contract/alert |
| seed_value | text | tx hash or address |
| time_window_hours | int | 默认 6 |
| depth | enum | quick/full/full_replay |
| status | enum | workflow status |
| severity | enum | unknown/low/medium/high/critical |
| attack_type | text | e.g. Access Control Abuse |
| loss_usd | numeric | nullable |
| confidence | enum | low/medium/high/partial |
| created_by | text | user id |
| created_at | timestamptz | |
| updated_at | timestamptz | |

## 3. Transaction

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | |
| case_id | uuid | |
| tx_hash | text | unique per case |
| block_number | bigint | |
| block_timestamp | timestamptz | |
| tx_index | int | |
| from_address | text | |
| to_address | text | nullable |
| nonce | bigint | |
| value_wei | numeric | |
| status | int | receipt status |
| method_selector | text | 0x... |
| method_name | text | decoded guess |
| phase | text | authorization/mint/borrow/bridge/remediation/unknown |
| artifact_status | enum | pending/running/done/failed/partial |

## 4. Artifact

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | |
| case_id | uuid | |
| tx_id | uuid | nullable for case-level artifacts |
| producer | text | txanalyzer_worker/decode_worker/etc |
| artifact_type | text | trace/source/opcode/receipt/report |
| object_path | text | s3/minio path |
| content_hash | text | sha256 |
| metadata | jsonb | |

## 5. Evidence

Evidence 是报告质量核心对象。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | |
| case_id | uuid | |
| tx_id | uuid | nullable |
| source_type | enum | receipt_log/trace_call/source_line/state_call/signature/balance_diff/artifact_summary/agent_inference |
| producer | text | worker name |
| claim_key | text | supported claim |
| raw_path | text | artifact path or external URL reference |
| decoded | jsonb | structured decoded evidence |
| confidence | enum | high/medium/low/partial |
| created_at | timestamptz | |

Evidence must be created only when it references raw data or deterministic worker output. `agent_inference` evidence can exist, but cannot alone support High confidence.

## 6. Finding

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | |
| case_id | uuid | |
| title | text | |
| finding_type | enum | access_control/multisig/fund_flow/contract_bug/loss/remediation/data_quality |
| severity | enum | critical/high/medium/low/info |
| confidence | enum | high/medium/low/partial |
| claim | text | concise claim |
| rationale | text | explanation |
| falsification | text | alternative explanations checked |
| evidence_ids | uuid[] | evidence support |
| reviewer_status | enum | pending/approved/rejected/more_evidence_needed |
| reviewer_comment | text | nullable |
| created_by | text | worker/agent/user |
| created_at | timestamptz | |
| updated_at | timestamptz | |

## 7. Report

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | |
| case_id | uuid | |
| version | int | |
| language | text | zh-CN/en-US |
| format | text | markdown/pdf/html/json |
| status | enum | draft/under_review/published/archived |
| object_path | text | report artifact path |
| content_hash | text | sha256 |
| evidence_coverage | jsonb | section coverage |
| created_by | text | |
| reviewed_by | text | nullable |
| created_at | timestamptz | |

## 8. JobRun

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | |
| case_id | uuid | |
| job_name | text | worker/activity name |
| status | enum | pending/running/success/failed/partial |
| input | jsonb | sanitized input |
| output | jsonb | summarized output |
| error | text | nullable |
| started_at | timestamptz | |
| ended_at | timestamptz | |

## 9. Confidence 规则

| Confidence | 条件 |
|---|---|
| high | 至少一个 deterministic evidence，且关键 claim 有 trace/log/source/state/signature 中至少一类支持 |
| medium | 缺少部分证据，但 receipt/log/ABI 或 state 支持主要结论 |
| partial | 证据链一段缺失，例如跨链目标链未闭环 |
| low | 主要来自模型推断或间接线索 |

## 10. Severity 规则

| Severity | 条件 |
|---|---|
| critical | 资金损失、协议级权限滥用、可复现严重漏洞 |
| high | 高风险漏洞或重要权限异常但未确认损失 |
| medium | 局部风险或证据不完整 |
| low | 低影响问题 |
| info | 背景事实或数据质量说明 |


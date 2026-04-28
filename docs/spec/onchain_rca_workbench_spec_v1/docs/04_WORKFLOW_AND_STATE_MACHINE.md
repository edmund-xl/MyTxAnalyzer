# 04 Workflow and State Machine

## 1. Case 状态

```text
CREATED
  → ENV_CHECKING
  → ENV_CHECKED
  → DISCOVERING_TRANSACTIONS
  → TRANSACTIONS_DISCOVERED
  → PULLING_ARTIFACTS
  → ARTIFACTS_PULLED
  → DECODING
  → DECODED
  → BUILDING_EVIDENCE
  → EVIDENCE_BUILT
  → RUNNING_FORENSICS
  → FORENSICS_DONE
  → RUNNING_RCA_AGENT
  → RCA_DONE
  → DRAFTING_REPORT
  → REPORT_DRAFTED
  → UNDER_REVIEW
  → PUBLISHED
```

失败状态：

```text
FAILED
PARTIAL
CANCELLED
```

## 2. 状态转移规则

| From | To | 条件 |
|---|---|---|
| CREATED | ENV_CHECKING | user runs case |
| ENV_CHECKING | ENV_CHECKED | environment check success or partial |
| ENV_CHECKED | DISCOVERING_TRANSACTIONS | minimum rpc_ok = true |
| DISCOVERING_TRANSACTIONS | TRANSACTIONS_DISCOVERED | related tx set created |
| TRANSACTIONS_DISCOVERED | PULLING_ARTIFACTS | at least 1 tx exists |
| PULLING_ARTIFACTS | ARTIFACTS_PULLED | all tx done or partial done |
| ARTIFACTS_PULLED | DECODING | at least one artifact manifest exists |
| DECODING | DECODED | decoded calls/logs saved |
| DECODED | BUILDING_EVIDENCE | deterministic evidence starts |
| BUILDING_EVIDENCE | EVIDENCE_BUILT | evidence rows inserted |
| EVIDENCE_BUILT | RUNNING_FORENSICS | module triggers evaluated |
| RUNNING_FORENSICS | FORENSICS_DONE | module outputs saved |
| FORENSICS_DONE | RUNNING_RCA_AGENT | evidence exists |
| RUNNING_RCA_AGENT | RCA_DONE | findings generated and schema-valid |
| RCA_DONE | DRAFTING_REPORT | findings exist |
| DRAFTING_REPORT | REPORT_DRAFTED | report markdown saved |
| REPORT_DRAFTED | UNDER_REVIEW | reviewer opens review or user submits review |
| UNDER_REVIEW | PUBLISHED | all required findings approved |

## 3. Workflow pseudocode

```python
async def case_analysis_workflow(case_id: str):
    update_case_status(case_id, "ENV_CHECKING")
    env = await run_activity(EnvironmentCheckWorker, case_id)
    update_case_status(case_id, "ENV_CHECKED")

    update_case_status(case_id, "DISCOVERING_TRANSACTIONS")
    txs = await run_activity(TxDiscoveryWorker, case_id, env)
    update_case_status(case_id, "TRANSACTIONS_DISCOVERED")

    update_case_status(case_id, "PULLING_ARTIFACTS")
    for tx in txs:
        await run_activity(TxAnalyzerWorker, case_id, tx)
    update_case_status(case_id, "ARTIFACTS_PULLED")

    update_case_status(case_id, "DECODING")
    await run_activity(DecodeWorker, case_id)
    await run_activity(ProxyResolverWorker, case_id)
    update_case_status(case_id, "DECODED")

    update_case_status(case_id, "BUILDING_EVIDENCE")
    await run_activity(BuildEvidenceWorker, case_id)
    update_case_status(case_id, "EVIDENCE_BUILT")

    update_case_status(case_id, "RUNNING_FORENSICS")
    await run_activity(ACLForensicsWorker, case_id)
    await run_activity(SafeForensicsWorker, case_id)
    await run_activity(FundFlowWorker, case_id)
    await run_activity(LossCalculatorWorker, case_id)
    update_case_status(case_id, "FORENSICS_DONE")

    update_case_status(case_id, "RUNNING_RCA_AGENT")
    await run_activity(RCAAgentWorker, case_id)
    update_case_status(case_id, "RCA_DONE")

    update_case_status(case_id, "DRAFTING_REPORT")
    await run_activity(ReportWorker, case_id)
    update_case_status(case_id, "REPORT_DRAFTED")
```

## 4. Module triggers

| Trigger | Module |
|---|---|
| tx touches Gnosis Safe / execTransaction / MultiSend | SafeForensicsWorker |
| RoleGranted / RoleRevoked / grantRole / AccessControl | ACLForensicsWorker |
| owner(), transferOwnership(), onlyOwner path | ACLForensicsWorker |
| ERC20 Transfer out from victim / attacker profit | FundFlowWorker |
| Borrow/Mint/Withdraw events | LendingFlow in FundFlowWorker |
| Bridge contract / LiFi / Across / Relay / Stargate | BridgeFlow in FundFlowWorker |
| Unverified source | DecompileWorker P1 |
| code exploit suspected | ReplayWorker P1 |

## 5. Retry policy

| Activity | Retry | Timeout |
|---|---:|---:|
| EnvironmentCheck | 2 | 60s |
| TxDiscovery | 3 | 180s |
| TxAnalyzer | 1 | 180s per tx |
| Decode | 2 | 120s |
| Forensics | 2 | 300s |
| RCAAgent | 1 | 600s |
| ReportWorker | 1 | 300s |

## 6. Partial success policy

A case can continue if:

- at least one tx artifact is available;
- receipt logs are available;
- at least one evidence row exists.

A case must stop before report if:

- no transactions discovered;
- no artifacts and no receipts;
- no evidence rows;
- Agent output invalid after retry.


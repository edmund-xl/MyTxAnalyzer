# 08 Evidence and QA Rules

## 1. 证据优先原则

系统报告中的关键事实必须绑定 evidence。

禁止出现：

- “攻击者利用了漏洞”但没有 trace/source/log 支持；
- “某 Owner 参与攻击”但没有 Safe signature evidence；
- “损失约 X 美元”但没有 token amount 和 price source；
- “合约无漏洞”但没有 validation path 审计。

## 2. Evidence 类型

| source_type | 说明 | High 可用 |
|---|---|---:|
| receipt_log | event log | 是 |
| trace_call | call trace/delegatecall | 是 |
| source_line | verified source path | 是 |
| state_call | historical eth_call result | 是 |
| signature | ecrecover/approvedHash/ERC1271 | 是 |
| balance_diff | ETH/ERC20 balance before/after | 是 |
| artifact_summary | artifact availability | 中性 |
| tx_metadata | block/time/from/to/method | 是，但不能单独证明复杂结论 |
| agent_inference | Agent 推断 | 不能单独 High |

## 3. Finding QA Gates

### 3.1 Access Control Gate

High-confidence access-control finding 必须满足至少两项：

- RoleGranted/RoleRevoked event；
- grantRole/addRole trace；
- historical `hasRole`/`getRoleAdmin` eth_call；
- source path showing `onlyRole` / ACL check；
- later attack tx uses the granted role.

### 3.2 Multisig Gate

High-confidence multisig finding 必须满足：

- Safe address identified；
- threshold and owners retrieved；
- `execTransaction` decoded；
- signer evidence from ECDSA ecrecover / approvedHash / ERC1271；
- submitter from tx.from；
- internal actions decoded or logs verified.

### 3.3 Fund Flow Gate

High-confidence fund-flow finding 必须满足至少两项：

- ERC20 Transfer logs；
- ETH balance diff / call value；
- DEX swap event / router trace；
- borrow/withdraw/mint event；
- bridge deposit event；
- destination chain fill event for cross-chain claim.

### 3.4 Contract Bug Gate

High-confidence contract bug finding 必须满足：

- vulnerable function identified；
- validation bypass or missing check shown in source/trace；
- write-object credited/debited verified；
- exploit path explains profit；
- optional replay if feasible.

### 3.5 No-vulnerability Claim Gate

“合约代码本身没有漏洞”这种结论必须满足：

- 关键函数源码已验证；
- permission/cap/oracle/health-factor gates 已逐项检查；
- trace 表明检查被正常执行；
- 检查通过原因来自权限或配置状态，而不是代码绕过。

## 4. Report QA Gates

| Gate | 发布前要求 |
|---|---|
| Chain Data Gate | tx metadata、receipt、logs 已拉取 |
| Artifact Gate | TxAnalyzer artifacts 成功或有降级说明 |
| Timeline Gate | phase 顺序无明显缺口 |
| Root Cause Gate | 根因解释完整 profit path |
| Asset Gate | 损失金额有链上证据 |
| Permission Gate | 权限类 finding 证据完整 |
| Signature Gate | 多签/签名 finding 证据完整 |
| Data Reliability Gate | 缺失项明确列出 |
| Review Gate | 高风险 finding approved |

## 5. Confidence downgrade rules

| 情况 | 自动降级 |
|---|---|
| 无 trace | high → medium |
| 无 source | high → medium/partial |
| 无 debug trace 且需要 ecrecover cross-check | high → medium unless eth_keys recovery sufficient and approved by reviewer |
| 跨链目标链无 confirmation | destination claim → partial |
| 只有 Agent inference | low |
| 价格源缺失 | USD loss → partial/unknown |

## 6. Evidence coverage metric

每个 report section 保存 coverage：

```json
{
  "section": "Root Cause",
  "claims_total": 5,
  "claims_supported": 5,
  "unsupported_claims": [],
  "coverage": 1.0
}
```

Report cannot be `PUBLISHED` if any critical section coverage < 0.8.

## 7. Reviewer policy

强制人工审核：

- 指名 Owner/团队/项目方有恶意；
- 认定 rug；
- 认定合约无漏洞；
- 认定特定私钥泄露；
- 估算重大损失金额；
- 对外发布报告。


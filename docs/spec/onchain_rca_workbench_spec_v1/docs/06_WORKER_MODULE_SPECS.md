# 06 Worker Module Specifications

## 1. 通用 Worker Contract

所有 worker 必须遵守：

```python
class WorkerResult(BaseModel):
    case_id: str
    worker_name: str
    status: Literal["success", "partial", "failed"]
    summary: dict
    artifacts: list[str]
    evidence_ids: list[str]
    error: str | None = None
```

每个 worker 必须：

1. 创建 `job_runs` 记录。
2. 保存 raw output 到 artifact store。
3. 保存结构化 output 到数据库。
4. 输出 evidence_ids。
5. 支持 idempotency；重复执行不能重复插入相同 evidence。

## 2. EnvironmentCheckWorker

### 输入

- case_id
- network_key

### 外部调用

| 调用 | 目的 |
|---|---|
| `eth_chainId` | 验证 RPC 链 ID |
| `eth_getBlockByNumber('latest')` | 验证 RPC 连通 |
| `trace_transaction` with sample tx if available | 检查 trace 支持 |
| `debug_traceTransaction` with sample tx if available | 检查 debug trace 支持 |
| Explorer `getsourcecode` | 检查 Explorer API |
| `eth_call` with block number | 检查 historical call |

### 输出

```json
{
  "rpc_ok": true,
  "chain_id": 4326,
  "trace_transaction_ok": true,
  "debug_trace_transaction_ok": true,
  "explorer_ok": true,
  "historical_call_ok": true,
  "degradation_notes": []
}
```

## 3. TxDiscoveryWorker

### 输入

- seed_type
- seed_value
- time_window_hours

### 方法

#### seed_type=transaction

1. 获取 seed tx receipt 和 metadata。
2. 取 seed from/to。
3. 拉 from address txlist，在时间窗口内筛选。
4. 从 receipt logs 找 touched tokens/contracts。
5. 从 trace 找 touched contracts。
6. 标记同 nonce 序列交易。

#### seed_type=address

1. 拉地址 txlist。
2. 按时间窗口筛选。
3. 对每笔 tx 取 method selector。
4. 根据 selector/logs 初步 phase 分类。

#### seed_type=contract

1. 拉 contract txlist。
2. 找异常大额 transfer/borrow/mint/bridge。
3. 需要用户指定时间窗口。

### 输出

- transactions rows
- phase_guess
- discovery artifact

## 4. TxAnalyzerWorker

详见 `docs/07_TXANALYZER_INTEGRATION.md`。

### P0 行为

1. 为 network 生成 TxAnalyzer config。
2. 调用 TxAnalyzer CLI。
3. 收集 `transactions/<tx_hash>/`。
4. 上传 artifact store。
5. 创建 artifact manifest。
6. 生成 basic artifact evidence。

## 5. DecodeWorker

### 输入

- TxAnalyzer artifacts
- receipts
- ABI/source if available

### 功能

- decode top-level input
- decode nested trace calls where ABI available
- decode receipt logs
- selector lookup fallback
- event signature lookup fallback

### Evidence examples

```json
{
  "source_type": "receipt_log",
  "claim_key": "role_granted_to_attacker",
  "decoded": {
    "event": "RoleGranted",
    "role": "BRIDGE_ROLE",
    "account": "0xd801...",
    "sender": "0x4c24..."
  }
}
```

## 6. ProxyResolverWorker

### 支持类型

- Transparent Proxy
- UUPS Proxy
- Beacon Proxy
- Gnosis Safe Proxy
- EIP-1967 slots

### 方法

| 类型 | 方法 |
|---|---|
| EIP-1967 | read implementation/admin/beacon storage slots |
| Gnosis Safe | read singleton slot / VERSION / getOwners / getThreshold |
| Unknown | bytecode fingerprint + source hints |

## 7. ACLForensicsWorker

### Trigger

- RoleGranted/RoleRevoked event
- grantRole/revokeRole/addXxxAdmin selector
- owner/transferOwnership
- Aave ACLManager function
- onlyOwner/onlyRole path in source

### 方法

1. 收集 role/owner 变更事件。
2. 对关键 block 执行 historical eth_call。
3. 解析源码中的 validation gates。
4. 把“权限被授予谁”和“权限在哪里被使用”连接起来。

### 输出 finding

- 攻击者获得角色。
- 权限检查通过原因。
- 权限授予交易来源。

## 8. SafeForensicsWorker

### Trigger

- contract is Gnosis Safe
- selector `execTransaction`
- selector `multiSend`
- Safe events

### 方法

1. 调用 `VERSION()`、`getThreshold()`、`getOwners()`。
2. decode `execTransaction` 参数。
3. decode signatures blob。
4. 对 ECDSA signature 计算 Safe tx hash 并 ecrecover。
5. 对 approvedHash signature 查 approved hash 或 trace。
6. decode MultiSend packed transactions。
7. 对比 attack 和 remediation signer matrix。

### 输出

```json
{
  "safe": "0x4c24...",
  "version": "1.3.0",
  "threshold": 2,
  "owners": ["0x7312...", "0x2bce...", "0xb483..."],
  "transactions": [
    {
      "tx_hash": "0xb96c...",
      "submitter": "0x2bce...",
      "signers": [
        {"address": "0x2bce...", "method": "approvedHash"},
        {"address": "0x7312...", "method": "ECDSA"}
      ],
      "internal_actions": []
    }
  ]
}
```

## 9. FundFlowWorker

### Trigger

- ERC20 Transfer logs
- ETH value transfers
- Borrow/Mint/Withdraw events
- DEX router calls
- Bridge calls/events

### 方法

1. 构建 address balance diff。
2. 汇总 ERC20 Transfer logs。
3. 识别借贷协议 events。
4. 识别 DEX swap route。
5. 识别 bridge deposit/fill。
6. 估算损失金额。

### 输出

- fund flow graph nodes/edges
- loss table
- bridge transfer table

## 10. LossCalculatorWorker

### 规则

- 稳定币按实际 token decimals 转换。
- ETH 估值需要显式 price_source。
- 如果没有价格源，输出 token-denominated loss，USD 标记 unknown。
- 不得凭 Agent 估算损失。

## 11. RCAAgentWorker

### 输入

- case summary
- transactions
- evidence
- module outputs
- artifact summaries

### 输出

必须符合 `schemas/finding.schema.json`。

Agent 不允许：

- 输出没有 evidence_ids 的 High finding；
- 把推断写成事实；
- 修改原始链上数据；
- 隐藏不确定性。

## 12. ReportWorker

### 输入

- approved/pending findings
- evidence
- timeline
- fund flow
- report template

### 输出

- Markdown P0
- JSON P0
- PDF P1


# 07 TxAnalyzer Integration Specification

## 1. 是否使用 TxAnalyzer

是。TxAnalyzer 是本系统的 P0 核心能力，不是可选项。

系统使用 TxAnalyzer 完成：

- EVM transaction trace 拉取；
- 合约源码 / ABI 拉取；
- opcode 级执行日志导出；
- selector mapping；
- TxAnalyzer 自带交易级分析产物读取；
- 为后续 Evidence、RCA Agent、Report 提供底层 artifacts。

## 2. 集成方式

MVP 使用 subprocess 调用 TxAnalyzer CLI，不直接复制或修改 TxAnalyzer 源码。

推荐路径：

```text
/opt/txanalyzer
```

可以通过以下方式安装：

1. Git submodule；
2. Docker image 中 clone；
3. host mount volume。

## 3. TxAnalyzer 命令

```bash
cd /opt/txanalyzer
python scripts/pull_artifacts.py --network <network_key> --tx <tx_hash> --timeout 120
```

可选参数：

```bash
--skip-opcode
--reuse-log
```

当 `debug_traceTransaction` 不可用时，必须追加 `--skip-opcode`，并在 case data quality 中标记降级。

## 4. Network config 生成

系统维护自己的 `networks` 表。TxAnalyzerWorker 在运行前生成 TxAnalyzer 的 `config.json`。

示例：

```json
{
  "networks": {
    "megaeth": {
      "name": "MegaETH Mainnet",
      "rpc_url": "${MEGAETH_RPC_URL}",
      "etherscan_api_key": "${MEGAETH_EXPLORER_API_KEY}",
      "etherscan_base_url": "https://api.etherscan.io/v2/api",
      "chain_id": 4326
    }
  },
  "default_network": "megaeth"
}
```

注意：不要把 secret 写入数据库明文或提交到代码仓库。运行时从环境变量替换。

## 5. 输入 contract

```python
class TxAnalyzerJobInput(BaseModel):
    case_id: str
    network_key: str
    tx_hash: str
    timeout_seconds: int = 120
    skip_opcode: bool = False
```

## 6. 输出 contract

```python
class TxAnalyzerJobOutput(BaseModel):
    case_id: str
    tx_hash: str
    status: Literal["success", "partial", "failed"]
    local_artifact_dir: str
    object_store_prefix: str
    files_imported: int
    manifest_path: str
    stdout_path: str
    stderr_path: str
    error: str | None
```

## 7. Artifact import

TxAnalyzerWorker 必须把：

```text
/opt/txanalyzer/transactions/<tx_hash>/
```

完整复制到：

```text
s3://<bucket>/cases/<case_id>/transactions/<tx_hash>/txanalyzer/
```

同时生成 manifest：

```json
{
  "producer": "txanalyzer_worker",
  "tx_hash": "0x...",
  "network_key": "megaeth",
  "source_dir": "/opt/txanalyzer/transactions/0x...",
  "object_prefix": "cases/case_001/transactions/0x.../txanalyzer/",
  "files": [
    {
      "path": "trace/call_trace.json",
      "sha256": "...",
      "size_bytes": 12345,
      "artifact_type": "trace"
    }
  ]
}
```

## 8. Artifact type mapping

| TxAnalyzer 文件/目录 | 系统 artifact_type |
|---|---|
| trace | trace |
| opcode | opcode |
| contract_sources | source |
| contracts | contract_metadata |
| analysis/result.md | txanalyzer_analysis |
| README.md | artifact_readme |
| tx_report.txt | tx_report |
| stdout/stderr | execution_log |

文件名可能随 TxAnalyzer 版本变化，worker 必须通过目录遍历生成 manifest，不依赖单一固定文件名。

## 9. Evidence 生成

TxAnalyzerWorker 本身至少生成以下 evidence：

```json
{
  "source_type": "artifact_summary",
  "producer": "txanalyzer_worker",
  "claim_key": "txanalyzer_artifacts_available",
  "decoded": {
    "tx_hash": "0x...",
    "has_trace": true,
    "has_source": true,
    "has_opcode": true,
    "file_count": 42
  },
  "confidence": "high"
}
```

如果 opcode 缺失：

```json
{
  "claim_key": "opcode_trace_unavailable",
  "confidence": "partial",
  "decoded": {
    "reason": "debug_traceTransaction unavailable or --skip-opcode used"
  }
}
```

## 10. 错误处理

| 错误 | 行为 |
|---|---|
| command timeout | mark tx artifact_status=failed, job_run failed |
| nonzero exit code | store stdout/stderr, mark failed |
| directory missing | failed |
| partial files | partial, continue workflow |
| network config missing | fail case before TxAnalyzer |

## 11. 许可注意

TxAnalyzer 仓库使用 GPL-3.0 license。MVP 使用外部 CLI/subprocess 调用，减少直接代码合并；如果后续要把 TxAnalyzer 代码直接合入闭源产品，需要确认 GPL-3.0 许可影响。

## 12. 为什么不能只用 TxAnalyzer

TxAnalyzer 是底层 artifact 和交易级 RCA 的核心，但完整报告还需要系统额外实现：

- 多交易聚类；
- Safe signer recovery；
- ACL 权限链追溯；
- 跨链资金流；
- evidence/finding 数据模型；
- 审核 workflow；
- 报告模板和导出。

因此架构是：

```text
TxAnalyzer artifacts
  → deterministic decoding
  → forensics modules
  → structured evidence
  → RCA Agent
  → reviewable report
```


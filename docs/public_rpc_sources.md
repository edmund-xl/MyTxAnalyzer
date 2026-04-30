# 公共 RPC 来源 / Public RPC Sources

## 中文

这些 endpoint 是本地 smoke test 的非敏感默认值。它们通常有速率限制；如果要做重度 RCA、archive-state 读取或 trace/debug 调用，应替换为专用 RPC provider。

### RPC 列表

| Network | Chain ID | Public RPC | Fallback RPC | Native token | Explorer | API notes |
| --- | ---: | --- | --- | --- | --- | --- |
| Ethereum Mainnet | 1 | `https://ethereum-rpc.publicnode.com` | `https://eth.llamarpc.com` | ETH | `https://etherscan.io` | Etherscan V2 使用 `https://api.etherscan.io/v2/api`，并带 `chainid=1`；需要 API key。 |
| BSC Mainnet | 56 | `https://bsc-dataseed1.binance.org/` | `https://bsc-dataseed.binance.org/` | BNB | `https://bscscan.com` | BscScan/Etherscan V2 endpoint 需要 API key。 |
| Arbitrum One | 42161 | `https://arbitrum-one-rpc.publicnode.com` | `https://arb1.arbitrum.io/rpc` | ETH | `https://arbiscan.io` | 公共 RPC 可用于基础 receipt；trace/debug 建议使用专用 provider。 |
| Base Mainnet | 8453 | `https://base-rpc.publicnode.com` | `https://mainnet.base.org` | ETH | `https://basescan.org` | 公共 RPC 可用于 smoke test 和 receipt hydration。 |
| Unichain Mainnet | 130 | `https://unichain-rpc.publicnode.com` | - | ETH | `https://uniscan.xyz` | PublicNode endpoint 支持基础 JSON-RPC。 |
| Taiko Mainnet | 167000 | `https://taiko-rpc.publicnode.com` | `https://rpc.mainnet.taiko.xyz` | ETH | `https://taikoscan.io` | 公共 RPC 可用于 seed 验证；trace/debug 建议使用专用 provider。 |
| MegaETH Mainnet | 4326 | `https://mainnet.megaeth.com/rpc` | - | ETH | MegaETH block explorer | 官方公共 RPC 支持基础 Ethereum JSON-RPC；trace/debug 可用性有限。 |
| Sui Mainnet | N/A | `https://fullnode.mainnet.sui.io:443` | - | SUI | `https://suiexplorer.com` | 非 EVM；使用 `sui_getTransactionBlock`、events 和 balanceChanges，TxAnalyzer 不适用。 |

### Provider 解析顺序

运行时优先读取用户自带密钥，不把密钥写入数据库：

1. 网络配置里的 `rpc_url_secret_ref`，例如 `ETH_RPC_URL`、`BASE_RPC_URL`、`SUI_RPC_URL`。
2. 网络专用 Explorer key，例如 `ETH_EXPLORER_API_KEY`、`BASE_EXPLORER_API_KEY`。
3. 通用 `ETHERSCAN_API_KEY`。
4. 公共 RPC fallback。

EnvironmentCheck 会记录 capability matrix：`eth_chainId`、`eth_getTransactionReceipt`、`trace_transaction`、`debug_traceTransaction`、Explorer `txlist/getsourcecode`、historical `eth_call`。公共 fallback 缺少 trace/debug 时属于降级，不应让全案失败。

### 本地验证

2026-04-26 本地验证结果：

| Network | `eth_chainId` result | `eth_blockNumber` check |
| --- | --- | --- |
| Ethereum Mainnet | `0x1` | OK |
| BSC Mainnet | `0x38` | OK |
| Arbitrum One | `0xa4b1` | OK |
| Base Mainnet | `0x2105` | OK |
| Unichain Mainnet | `0x82` | OK |
| Taiko Mainnet | `0x28c58` | OK |
| MegaETH Mainnet | `0x10e6` | OK |

### 来源

- BscScan public RPC node list: `https://docs.bscscan.com/misc-tools-and-utilities/public-rpc-nodes`
- MegaETH mainnet docs: `https://docs.megaeth.com/frontier`
- MegaETH RPC method docs: `https://docs.megaeth.com/rpc`
- PublicNode Ethereum endpoint: `https://ethereum-rpc.publicnode.com/`
- PublicNode multi-chain RPC directory: `https://www.publicnode.com/`
- LlamaNodes public RPC: `https://llamanodes.com/public-rpc`
- Etherscan V2 migration/API base path: `https://docs.etherscan.io/v2-migration`

实现说明：Web3.py 读取 BSC block 时需要 `ExtraDataToPOAMiddleware`，因为 BSC block header 使用 POA 风格的 `extraData`。

## English

These endpoints are non-secret defaults for local smoke tests. They are usually rate limited and should be replaced with a dedicated RPC provider for heavy RCA runs, archive-state reads, or trace/debug calls.

### RPC List

| Network | Chain ID | Public RPC | Fallback RPC | Native token | Explorer | API notes |
| --- | ---: | --- | --- | --- | --- | --- |
| Ethereum Mainnet | 1 | `https://ethereum-rpc.publicnode.com` | `https://eth.llamarpc.com` | ETH | `https://etherscan.io` | Etherscan V2 uses `https://api.etherscan.io/v2/api` with `chainid=1`; API key required. |
| BSC Mainnet | 56 | `https://bsc-dataseed1.binance.org/` | `https://bsc-dataseed.binance.org/` | BNB | `https://bscscan.com` | BscScan/Etherscan V2 endpoints require an API key. |
| Arbitrum One | 42161 | `https://arbitrum-one-rpc.publicnode.com` | `https://arb1.arbitrum.io/rpc` | ETH | `https://arbiscan.io` | Public RPC supports baseline receipts; dedicated provider recommended for trace/debug. |
| Base Mainnet | 8453 | `https://base-rpc.publicnode.com` | `https://mainnet.base.org` | ETH | `https://basescan.org` | Public RPC supports smoke tests and receipt hydration. |
| Unichain Mainnet | 130 | `https://unichain-rpc.publicnode.com` | - | ETH | `https://uniscan.xyz` | PublicNode endpoint supports baseline JSON-RPC. |
| Taiko Mainnet | 167000 | `https://taiko-rpc.publicnode.com` | `https://rpc.mainnet.taiko.xyz` | ETH | `https://taikoscan.io` | Public RPC supports seed validation; dedicated provider recommended for trace/debug. |
| MegaETH Mainnet | 4326 | `https://mainnet.megaeth.com/rpc` | - | ETH | MegaETH block explorer | Official public RPC supports baseline Ethereum JSON-RPC; trace/debug availability is limited. |
| Sui Mainnet | N/A | `https://fullnode.mainnet.sui.io:443` | - | SUI | `https://suiexplorer.com` | Non-EVM; uses `sui_getTransactionBlock`, events, and balanceChanges. TxAnalyzer does not apply. |

### Provider Resolution Order

Runtime resolution prefers bring-your-own keys and does not store secrets in the database:

1. The configured `rpc_url_secret_ref`, for example `ETH_RPC_URL`, `BASE_RPC_URL`, or `SUI_RPC_URL`.
2. Network-specific Explorer keys, for example `ETH_EXPLORER_API_KEY` or `BASE_EXPLORER_API_KEY`.
3. Generic `ETHERSCAN_API_KEY`.
4. Public RPC fallback.

EnvironmentCheck records a capability matrix covering `eth_chainId`, `eth_getTransactionReceipt`, `trace_transaction`, `debug_traceTransaction`, Explorer `txlist/getsourcecode`, and historical `eth_call`. Missing trace/debug support on public fallback is a degradation, not a full case failure.

### Local Validation

Local validation on 2026-04-26:

| Network | `eth_chainId` result | `eth_blockNumber` check |
| --- | --- | --- |
| Ethereum Mainnet | `0x1` | OK |
| BSC Mainnet | `0x38` | OK |
| Arbitrum One | `0xa4b1` | OK |
| Base Mainnet | `0x2105` | OK |
| Unichain Mainnet | `0x82` | OK |
| Taiko Mainnet | `0x28c58` | OK |
| MegaETH Mainnet | `0x10e6` | OK |

### Sources

- BscScan public RPC node list: `https://docs.bscscan.com/misc-tools-and-utilities/public-rpc-nodes`
- MegaETH mainnet docs: `https://docs.megaeth.com/frontier`
- MegaETH RPC method docs: `https://docs.megaeth.com/rpc`
- PublicNode Ethereum endpoint: `https://ethereum-rpc.publicnode.com/`
- PublicNode multi-chain RPC directory: `https://www.publicnode.com/`
- LlamaNodes public RPC: `https://llamanodes.com/public-rpc`
- Etherscan V2 migration/API base path: `https://docs.etherscan.io/v2-migration`

Implementation note: Web3.py needs `ExtraDataToPOAMiddleware` for BSC block reads because BSC block headers use POA-style `extraData`.

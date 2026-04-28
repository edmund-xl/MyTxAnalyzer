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

# 10 MegaETH Golden Case Acceptance Spec

## 1. 目的

使用 MegaETH Aave V3 攻击报告作为 golden case，验证系统是否能稳定复现样本报告质量。

本文件不是攻击事实完整来源；工程实现时需要用户提供完整 tx hash、RPC、Explorer API。当前样本报告中的若干 tx hash 是截断形式，因此测试数据需要补全。

## 2. Golden case 基本信息

| 字段 | 值 |
|---|---|
| Chain | MegaETH Mainnet |
| Chain ID | 4326 |
| Date | 2026-04-25 |
| Attack Window | 09:39:39 — 09:49:40 UTC+8 |
| Event Type | rug / access-control abuse |
| Loss | ~36.8 ETH + ~238,658 USDT |
| Analysis Goal | 复现攻击时间线、ACL 授权、多签 signer、mintUnbacked、borrow、swap、bridge、补救和损失测算 |

## 3. 已知关键地址

| 角色 | 地址 |
|---|---|
| Gnosis Safe / ACL Admin | 0x4c2444d88ad61b0842fba7ccdcb226260ebfa1bc |
| Attacker EOA | 0xd8010aca201f6113160200b8a521f35be9f94c24 |
| Owner 1 | 0x7312f0b280f4bbaa47fc6485809f1c5cc629d7bb |
| Owner 2 | 0x2bcef069eaea664397a28f99b0de5d4a4f78e23e |
| Owner 3 | 0xb4837962855a1594e7ade6b87daa3e8f4a34baed |

## 4. Expected Phases

| Phase | Expected behavior | Required evidence |
|---|---|---|
| Phase 0 | Safe `execTransaction` + `multiSend` grants 5 ACL roles to attacker | Safe decode, RoleGranted logs, signer recovery |
| Phase 1 | Attacker calls `setUnbackedMintCap(xUSD, 50B)` | PoolConfigurator trace, RISK_ADMIN role check |
| Phase 2 | Attacker calls `mintUnbacked` 4 × 500,000 xUSD | Pool trace, ACLManager.isBridge true, aToken mint logs |
| Phase 3 | Attacker approves Gateway delegation | decoded approveDelegation |
| Phase 4 | Attacker borrows ETH, USDT, xUSD | Borrow events, Transfer logs, balance diff |
| Phase 5 | xUSD swap to USDT and bridge ETH/USDT to L1 | DEX route, LiFi/Across/Relay bridge events |
| Remediation | Freeze reserves and revoke attacker roles | Safe txlist, RoleRevoked/freeze logs, signer matrix |

## 5. Expected role grants

System must detect that attacker receives all 5 roles:

- FLASH_BORROWER
- RISK_ADMIN
- BRIDGE
- ASSET_LISTING_ADMIN
- EMERGENCY_ADMIN

## 6. Expected multisig finding

System must detect:

- Safe threshold is 2/3.
- Owner 2 submitted the attack authorization transaction.
- Owner 2 signature type is approvedHash or equivalent pre-approval.
- Owner 1 provided ECDSA signature.
- Owner 3 did not sign the attack authorization.
- Owner 2 did not participate in remediation transactions.

## 7. Expected root cause

Accepted root cause wording:

> Aave V3 contract logic was not the direct vulnerability. The exploit path was enabled by Gnosis Safe ACL admin authorization: two Safe owners authorized an attacker EOA to receive all critical ACL roles, allowing the EOA to raise the unbacked mint cap, mint 2,000,000 xUSD aTokens without backing, and borrow/bridge real assets.

中文：

> Aave V3 合约代码本身不是直接漏洞；根因是 ACL Admin Gnosis Safe 的 2/3 多签授权把关键角色授予攻击者 EOA，攻击者因此能提高 unbacked mint cap、通过 `mintUnbacked` 凭空铸造 200 万 xUSD aToken，并借出 / 桥出真实资产。

## 8. Expected loss table

| Asset | Amount | Evidence required |
|---|---:|---|
| ETH | ~36.8 ETH | borrowETH, WETH withdraw, ETH transfer/balance diff |
| USDT direct | ~163,035.72 USDT | Borrow/Transfer logs |
| xUSD borrowed and swapped | ~75,683.93 xUSD → ~75,622 USDT | Borrow + DEX swap + bridge event |
| Total | ~238,658 USDT + ~36.8 ETH | fund flow aggregation |

## 9. Golden case acceptance tests

The system passes golden case if:

- It discovers or accepts the relevant attack tx set.
- It marks Phase 0 as authorization, not asset extraction.
- It identifies Safe as ACL Admin.
- It reads Safe owners and threshold.
- It decodes 5 role grants.
- It recovers or classifies two attack signers correctly.
- It identifies `setUnbackedMintCap` and `mintUnbacked`.
- It explains why `mintUnbacked` succeeded: attacker had BRIDGE role and cap was raised.
- It distinguishes contract logic from permission abuse.
- It reconstructs borrow and bridge amounts within tolerance.
- It marks any unconfirmed cross-chain details as partial.
- It generates a report with the required sections.

## 10. Sample case seed file

See `sample_case/megaeth_case_seed.yaml`.


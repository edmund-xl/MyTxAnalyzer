from __future__ import annotations

import os
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware


PUBLIC_NETWORK_INFO: dict[str, dict[str, Any]] = {
    "eth": {
        "rpc_urls": [
            "https://ethereum-rpc.publicnode.com",
            "https://eth.llamarpc.com",
        ],
        "chain_id": 1,
        "native_token": "ETH",
        "block_explorer_url": "https://etherscan.io",
        "explorer_api_base_url": "https://api.etherscan.io/v2/api",
        "notes": "Public endpoints are suitable for baseline JSON-RPC checks; trace/debug methods usually require a dedicated provider.",
    },
    "bsc": {
        "rpc_urls": [
            "https://bsc-dataseed1.binance.org/",
            "https://bsc-dataseed.binance.org/",
        ],
        "chain_id": 56,
        "native_token": "BNB",
        "block_explorer_url": "https://bscscan.com",
        "explorer_api_base_url": "https://api.etherscan.io/v2/api",
        "notes": "BscScan documents the Binance dataseed public RPC nodes. Explorer API access still needs an API key.",
    },
    "arbitrum": {
        "rpc_urls": [
            "https://arbitrum-one-rpc.publicnode.com",
            "https://arb1.arbitrum.io/rpc",
        ],
        "chain_id": 42161,
        "native_token": "ETH",
        "block_explorer_url": "https://arbiscan.io",
        "explorer_api_base_url": "https://api.etherscan.io/v2/api",
        "notes": "Public endpoints are suitable for baseline receipts; full traces usually require a dedicated archive/debug provider.",
    },
    "base": {
        "rpc_urls": [
            "https://base-rpc.publicnode.com",
            "https://mainnet.base.org",
        ],
        "chain_id": 8453,
        "native_token": "ETH",
        "block_explorer_url": "https://basescan.org",
        "explorer_api_base_url": "https://api.etherscan.io/v2/api",
        "notes": "Public endpoints are rate limited and should be replaced for bulk analysis.",
    },
    "unichain": {
        "rpc_urls": [
            "https://unichain-rpc.publicnode.com",
        ],
        "chain_id": 130,
        "native_token": "ETH",
        "block_explorer_url": "https://uniscan.xyz",
        "explorer_api_base_url": "https://api.etherscan.io/v2/api",
        "notes": "PublicNode Unichain endpoint supports baseline Ethereum JSON-RPC checks.",
    },
    "taiko": {
        "rpc_urls": [
            "https://taiko-rpc.publicnode.com",
            "https://rpc.mainnet.taiko.xyz",
        ],
        "chain_id": 167000,
        "native_token": "ETH",
        "block_explorer_url": "https://taikoscan.io",
        "explorer_api_base_url": "https://api.etherscan.io/v2/api",
        "notes": "Public endpoints are useful for seed receipt validation; trace/debug should use a dedicated provider.",
    },
    "megaeth": {
        "rpc_urls": [
            "https://mainnet.megaeth.com/rpc",
        ],
        "chain_id": 4326,
        "native_token": "ETH",
        "block_explorer_url": "https://www.megaexplorer.xyz",
        "explorer_api_base_url": "https://api.etherscan.io/v2/api",
        "notes": "MegaETH public RPC supports baseline Ethereum JSON-RPC methods and currently answers debug_traceTransaction; trace_transaction is not supported on the public endpoint.",
    },
    "sui": {
        "rpc_urls": [
            "https://fullnode.mainnet.sui.io:443",
        ],
        "chain_id": 0,
        "native_token": "SUI",
        "block_explorer_url": "https://suiexplorer.com",
        "explorer_api_base_url": None,
        "notes": "Sui is not EVM-compatible. Use Sui JSON-RPC methods such as sui_getChainIdentifier and sui_getTransactionBlock; TxAnalyzer does not apply.",
    },
}


def public_network_info(network_key: str) -> dict[str, Any]:
    return PUBLIC_NETWORK_INFO.get(network_key, {})


def resolve_rpc_url(network) -> tuple[str | None, str]:
    configured = os.getenv(network.rpc_url_secret_ref)
    if configured:
        return configured, f"env:{network.rpc_url_secret_ref}"
    fallback = public_network_info(network.key).get("rpc_urls", [])
    if fallback:
        return fallback[0], "public_rpc_fallback"
    return None, "missing"


def resolve_explorer_api_key(network) -> tuple[str | None, str]:
    """Resolve explorer API key without treating empty env vars as configured."""
    refs = []
    if network.explorer_api_key_secret_ref:
        refs.append(network.explorer_api_key_secret_ref)
    refs.extend(["ETHERSCAN_API_KEY", f"{str(network.key).upper()}_EXPLORER_API_KEY"])
    seen: set[str] = set()
    for ref in refs:
        if not ref or ref in seen:
            continue
        seen.add(ref)
        value = os.getenv(ref)
        if value:
            return value, f"env:{ref}"
    return None, "missing"


def apply_network_middlewares(w3: Web3, network_key: str) -> Web3:
    if network_key == "bsc":
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3

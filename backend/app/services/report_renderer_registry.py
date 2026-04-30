from __future__ import annotations

from typing import Any


class ReportRendererRegistry:
    """Classify a case into a reusable attack-type renderer key."""

    ORDERED_RENDERERS = [
        "address_scope_boundary",
        "amm_rounding_liquidity",
        "collateral_solvency_bypass",
        "cross_contract_reentrancy",
        "oracle_price_manipulation",
        "access_control_or_forwarder",
        "reward_accounting",
        "bridge_message_verification",
        "generic_fallback",
    ]

    def select(self, case, evidence: list, findings: list) -> str:
        text = " ".join(
            [
                str(case.attack_type or ""),
                str(case.seed_type or ""),
                str(case.root_cause_one_liner or ""),
                " ".join(str(f.finding_type) for f in findings),
                " ".join(str(item.claim_key) for item in evidence),
            ]
        ).lower()
        if "address_scope_boundary" in text or ("address" in text and "address_discovery_explorer_missing" in text):
            return "address_scope_boundary"
        if "bunni" in text or "rounding" in text or "liquidity" in text and "amm" in text:
            return "amm_rounding_liquidity"
        if "revert" in text or "collateralized" in text or "solvency" in text:
            return "collateral_solvency_bypass"
        if "reentrancy" in text or "gmx" in text:
            return "cross_contract_reentrancy"
        if "oracle" in text or "price" in text or "kiloex" in text:
            return "oracle_price_manipulation"
        if "access_control" in text or "forwarder" in text or "role" in text or "cork" in text:
            return "access_control_or_forwarder"
        if "scallop" in text or "reward" in text:
            return "reward_accounting"
        if "bridge" in text or "layerzero" in text or "message" in text or "kelp" in text:
            return "bridge_message_verification"
        return "generic_fallback"

    def metadata(self, renderer_key: str) -> dict[str, Any]:
        return {
            "renderer_key": renderer_key,
            "renderer_family": renderer_key if renderer_key in self.ORDERED_RENDERERS else "generic_fallback",
            "stable_sections": [
                "TL;DR",
                "概述",
                "涉事方",
                "攻击时间线",
                "数据流图",
                "根因分析",
                "财务影响",
                "分析链路与方法论",
                "总分析时长",
                "附录",
            ],
        }

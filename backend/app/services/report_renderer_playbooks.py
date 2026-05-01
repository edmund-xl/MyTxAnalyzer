from __future__ import annotations

from pydantic import BaseModel, Field


class AttackRendererPlaybook(BaseModel):
    family: str
    required_evidence_types: list[str] = Field(default_factory=list)
    optional_evidence_types: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    common_alternative_hypotheses: list[str] = Field(default_factory=list)
    remediation_templates: list[str] = Field(default_factory=list)
    qa_rule_ids: list[str] = Field(default_factory=list)


PLAYBOOKS: dict[str, AttackRendererPlaybook] = {
    "address_scope_boundary": AttackRendererPlaybook(
        family="address_scope_boundary",
        required_evidence_types=["provider_degradation", "artifact_summary"],
        invariants=["A standalone address is not an attack scope without txlist, receipt, trace, or fund-flow evidence."],
        common_alternative_hypotheses=["attacker address", "victim contract", "unrelated address"],
        remediation_templates=["Provide a seed transaction or configure Explorer txlist enrichment before publishing RCA conclusions."],
        qa_rule_ids=["RQ-BLOCK-006"],
    ),
    "amm_rounding_liquidity": AttackRendererPlaybook(
        family="amm_rounding_liquidity",
        required_evidence_types=["tx_metadata", "receipt_log", "balance_diff"],
        optional_evidence_types=["trace_call", "source_line"],
        invariants=["Liquidity accounting must preserve pool share value across deposits, withdrawals, and idle balance updates."],
        common_alternative_hypotheses=["oracle manipulation", "reentrancy", "access-control bypass", "normal arbitrage"],
        remediation_templates=[
            "Patch rounding direction and enforce invariant tests around share accounting.",
            "Add monitoring for repeated small withdrawals that move idle/active balance ratios.",
        ],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-WARN-004", "RQ-WARN-005"],
    ),
    "collateral_solvency_bypass": AttackRendererPlaybook(
        family="collateral_solvency_bypass",
        required_evidence_types=["tx_metadata", "receipt_log", "balance_diff"],
        optional_evidence_types=["trace_call", "source_line", "state_call"],
        invariants=["When collateral is modified while active debt exists, the position must remain solvent after the state transition."],
        common_alternative_hypotheses=["oracle price manipulation", "reentrancy", "access-control bypass", "normal user withdrawal", "accounting mismatch"],
        remediation_templates=[
            "Enforce solvency checks on every collateral mutation path.",
            "Add invariant tests for active-debt collateral modification.",
            "Monitor collateral state changes where outstanding debt remains non-zero.",
        ],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-BLOCK-004", "RQ-WARN-004", "RQ-WARN-005", "RQ-WARN-006"],
    ),
    "cross_contract_reentrancy": AttackRendererPlaybook(
        family="cross_contract_reentrancy",
        required_evidence_types=["tx_metadata", "trace_call"],
        optional_evidence_types=["receipt_log", "source_line"],
        invariants=["Reentrancy guards must cover cross-contract state transitions that share solvency or accounting state."],
        common_alternative_hypotheses=["oracle manipulation", "privileged access", "normal liquidation", "accounting mismatch"],
        remediation_templates=["Extend reentrancy controls to the shared cross-contract state boundary.", "Add trace-based regression tests for callback paths."],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-WARN-004", "RQ-WARN-005"],
    ),
    "oracle_price_manipulation": AttackRendererPlaybook(
        family="oracle_price_manipulation",
        required_evidence_types=["tx_metadata", "receipt_log", "state_call"],
        optional_evidence_types=["trace_call", "balance_diff"],
        invariants=["Protocol-critical valuation must not be derived from manipulable spot state inside the exploit transaction window."],
        common_alternative_hypotheses=["access-control bypass", "reentrancy", "liquidity accounting bug", "normal market movement"],
        remediation_templates=["Use TWAP or bounded oracle reads for collateral and settlement paths.", "Monitor price deviations during borrow, mint, or settlement calls."],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-BLOCK-004", "RQ-WARN-004"],
    ),
    "access_control_or_forwarder": AttackRendererPlaybook(
        family="access_control_or_forwarder",
        required_evidence_types=["tx_metadata", "receipt_log", "signature"],
        optional_evidence_types=["trace_call", "source_line"],
        invariants=["Privileged state transitions must require an authorized caller, signer, or trusted forwarder context."],
        common_alternative_hypotheses=["private-key compromise", "governance action", "normal admin operation", "missing input validation"],
        remediation_templates=["Constrain privileged functions to explicit roles and forwarder allowlists.", "Add monitoring for privileged role changes and meta-transaction senders."],
        qa_rule_ids=["RQ-BLOCK-001", "RQ-BLOCK-003", "RQ-WARN-004"],
    ),
    "reward_accounting": AttackRendererPlaybook(
        family="reward_accounting",
        required_evidence_types=["tx_metadata", "receipt_log", "balance_diff"],
        optional_evidence_types=["trace_call", "source_line"],
        invariants=["Reward accounting must tie claimable rewards to actual stake, pool state, and redemption caps."],
        common_alternative_hypotheses=["oracle manipulation", "normal reward claim", "access-control bypass", "accounting mismatch"],
        remediation_templates=["Disable deprecated reward paths or enforce stake-linked reward caps.", "Add monitoring for reward redemption outliers."],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-BLOCK-004", "RQ-WARN-004"],
    ),
    "bridge_message_verification": AttackRendererPlaybook(
        family="bridge_message_verification",
        required_evidence_types=["tx_metadata", "receipt_log"],
        optional_evidence_types=["trace_call", "signature", "external_report"],
        invariants=["Target-chain asset release must correspond to a valid source-chain lock, burn, or message attestation."],
        common_alternative_hypotheses=["normal bridge withdrawal", "forged inbound packet", "DVN/signature failure", "downstream lending exploit"],
        remediation_templates=["Raise message verification thresholds and require source-chain packet reconciliation.", "Monitor target-chain releases without matching source-chain events."],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-BLOCK-004", "RQ-WARN-004", "RQ-WARN-005"],
    ),
    "generic_fallback": AttackRendererPlaybook(
        family="generic_fallback",
        required_evidence_types=["tx_metadata"],
        optional_evidence_types=["receipt_log", "balance_diff", "trace_call", "source_line"],
        invariants=["A report conclusion must be no stronger than its bound evidence."],
        common_alternative_hypotheses=["normal transaction", "fund movement only", "contract bug", "access-control issue", "market/oracle issue"],
        remediation_templates=["Collect missing deterministic evidence before prescribing protocol changes."],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-WARN-004", "RQ-WARN-005"],
    ),
}


def get_playbook(renderer_family: str) -> AttackRendererPlaybook:
    return PLAYBOOKS.get(renderer_family, PLAYBOOKS["generic_fallback"])

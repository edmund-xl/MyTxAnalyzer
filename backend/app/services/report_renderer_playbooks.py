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
        invariants=["只有地址、没有交易列表、交易收据、调用跟踪或资金流证据时，不能把该地址直接定义为攻击范围。"],
        common_alternative_hypotheses=["攻击者地址", "受害合约", "无关地址"],
        remediation_templates=["在发布根因分析结论前，先补充核心交易哈希，或配置区块浏览器交易列表能力。"],
        qa_rule_ids=["RQ-BLOCK-006"],
    ),
    "amm_rounding_liquidity": AttackRendererPlaybook(
        family="amm_rounding_liquidity",
        required_evidence_types=["tx_metadata", "receipt_log", "balance_diff"],
        optional_evidence_types=["trace_call", "source_line"],
        invariants=["流动性会计在存入、赎回和闲置余额更新过程中，必须保持池份额价值守恒。"],
        common_alternative_hypotheses=["预言机操纵", "重入", "访问控制绕过", "正常套利"],
        remediation_templates=[
            "修正舍入方向，并围绕份额会计增加不变量测试。",
            "增加重复小额赎回监控，重点观察闲置余额和活跃余额比例异常变化。",
        ],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-WARN-004", "RQ-WARN-005"],
    ),
    "collateral_solvency_bypass": AttackRendererPlaybook(
        family="collateral_solvency_bypass",
        required_evidence_types=["tx_metadata", "receipt_log", "balance_diff"],
        optional_evidence_types=["trace_call", "source_line", "state_call"],
        invariants=["当头寸仍有未偿还债务时，任何抵押物变更之后都必须保持偿付能力。"],
        common_alternative_hypotheses=["预言机价格操纵", "重入", "访问控制绕过", "正常用户提款", "会计不一致"],
        remediation_templates=[
            "在每一条抵押物变更路径上强制执行偿付能力检查。",
            "为带债抵押物变更增加不变量测试。",
            "监控未偿债务不为零时发生的抵押物状态变化。",
        ],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-BLOCK-004", "RQ-WARN-004", "RQ-WARN-005", "RQ-WARN-006"],
    ),
    "cross_contract_reentrancy": AttackRendererPlaybook(
        family="cross_contract_reentrancy",
        required_evidence_types=["tx_metadata", "trace_call"],
        optional_evidence_types=["receipt_log", "source_line"],
        invariants=["重入保护必须覆盖共享偿付或会计状态的跨合约状态转换。"],
        common_alternative_hypotheses=["预言机操纵", "特权访问", "正常清算", "会计不一致"],
        remediation_templates=["把重入控制扩展到跨合约共享状态边界。", "为回调路径增加基于调用跟踪的回归测试。"],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-WARN-004", "RQ-WARN-005"],
    ),
    "oracle_price_manipulation": AttackRendererPlaybook(
        family="oracle_price_manipulation",
        required_evidence_types=["tx_metadata", "receipt_log", "state_call"],
        optional_evidence_types=["trace_call", "balance_diff"],
        invariants=["协议关键估值不能依赖攻击交易窗口内可被操纵的即时状态。"],
        common_alternative_hypotheses=["访问控制绕过", "重入", "流动性会计缺陷", "正常市场波动"],
        remediation_templates=["在抵押和结算路径中使用时间加权价格或带边界的预言机读取。", "监控借款、铸造或结算调用中的价格偏离。"],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-BLOCK-004", "RQ-WARN-004"],
    ),
    "access_control_or_forwarder": AttackRendererPlaybook(
        family="access_control_or_forwarder",
        required_evidence_types=["tx_metadata", "receipt_log", "signature"],
        optional_evidence_types=["trace_call", "source_line"],
        invariants=["特权状态变更必须要求授权调用者、授权签名者或可信转发器上下文。"],
        common_alternative_hypotheses=["私钥泄露", "治理操作", "正常管理员操作", "输入校验缺失"],
        remediation_templates=["把特权函数限制到明确角色和可信转发器白名单。", "增加特权角色变更和元交易发送者监控。"],
        qa_rule_ids=["RQ-BLOCK-001", "RQ-BLOCK-003", "RQ-WARN-004"],
    ),
    "reward_accounting": AttackRendererPlaybook(
        family="reward_accounting",
        required_evidence_types=["tx_metadata", "receipt_log", "balance_diff"],
        optional_evidence_types=["trace_call", "source_line"],
        invariants=["奖励会计必须把可领取奖励绑定到真实质押、池状态和赎回上限。"],
        common_alternative_hypotheses=["预言机操纵", "正常奖励领取", "访问控制绕过", "会计不一致"],
        remediation_templates=["禁用废弃奖励路径，或强制执行与真实质押绑定的奖励上限。", "增加异常奖励赎回监控。"],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-BLOCK-004", "RQ-WARN-004"],
    ),
    "bridge_message_verification": AttackRendererPlaybook(
        family="bridge_message_verification",
        required_evidence_types=["tx_metadata", "receipt_log"],
        optional_evidence_types=["trace_call", "signature", "external_report"],
        invariants=["目标链资产释放必须对应有效的源链锁定、销毁或消息证明。"],
        common_alternative_hypotheses=["正常跨链提款", "伪造入站消息", "验证网络或签名失效", "下游借贷协议被攻击"],
        remediation_templates=["提高跨链消息验证阈值，并要求源链消息与目标链释放逐笔核对。", "监控没有匹配源链事件的目标链资产释放。"],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-BLOCK-004", "RQ-WARN-004", "RQ-WARN-005"],
    ),
    "generic_fallback": AttackRendererPlaybook(
        family="generic_fallback",
        required_evidence_types=["tx_metadata"],
        optional_evidence_types=["receipt_log", "balance_diff", "trace_call", "source_line"],
        invariants=["报告结论的强度不能超过其绑定证据的强度。"],
        common_alternative_hypotheses=["正常交易", "仅有资金移动", "合约缺陷", "访问控制问题", "市场或预言机问题"],
        remediation_templates=["在提出协议修改建议前，先补齐缺失的确定性证据。"],
        qa_rule_ids=["RQ-BLOCK-003", "RQ-WARN-004", "RQ-WARN-005"],
    ),
}


def get_playbook(renderer_family: str) -> AttackRendererPlaybook:
    return PLAYBOOKS.get(renderer_family, PLAYBOOKS["generic_fallback"])

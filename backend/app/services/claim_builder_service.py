from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import DiagramSpec, JobRun
from app.models.report_quality import AlternativeHypothesis, ClaimGraph, EvidenceRef, FinancialImpactItem, ReportClaim
from app.services.case_service import CaseService
from app.services.evidence_service import DETERMINISTIC_EVIDENCE_TYPES, EvidenceService
from app.services.finding_service import FindingService
from app.services.report_renderer_playbooks import get_playbook


class ClaimBuilderService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def build_for_report(self, case_id: str, report_version: int, renderer_family: str) -> ClaimGraph:
        case_service = CaseService(self.db)
        case = case_service.get_case(case_id)
        transactions = case_service.list_transactions(case_id)
        timeline = case_service.timeline(case_id)
        evidence = EvidenceService(self.db).list_for_case(case_id)
        findings = [item for item in FindingService(self.db).list_for_case(case_id) if item.reviewer_status != "rejected"]
        diagrams = list(self.db.scalars(select(DiagramSpec).where(DiagramSpec.case_id == case_id)).all())
        jobs = list(self.db.scalars(select(JobRun).where(JobRun.case_id == case_id).order_by(JobRun.created_at)).all())
        report_type = self._report_type(case, transactions, evidence, findings)
        playbook = get_playbook(renderer_family)
        evidence_by_id = {item.id: item for item in evidence}
        all_evidence_ids = [item.id for item in evidence]

        claims: list[ReportClaim] = []
        financial: list[FinancialImpactItem] = []
        boundaries = self._global_boundaries(case, evidence, jobs, report_type)

        if report_type == "address_boundary":
            claims.extend(self._address_boundary_claims(case, evidence, all_evidence_ids))
        elif report_type == "external_event_preanalysis":
            claims.extend(self._external_event_claims(case, evidence, all_evidence_ids))
        elif report_type == "transaction_preanalysis":
            claims.extend(self._transaction_preanalysis_claims(case, transactions, evidence))
            financial.extend(self._transaction_financial_items(evidence))
        else:
            claims.extend(self._full_rca_claims(case, transactions, timeline, evidence, findings, renderer_family, playbook.invariants))
            financial.extend(self._attack_financial_items(case, evidence))
            claims.extend(self._remediation_claims(playbook.remediation_templates, claims))

        alternatives = self._alternative_hypotheses(report_type, renderer_family, findings, evidence_by_id)
        metadata = {
            "report_type": report_type,
            "transaction_count": len(transactions),
            "evidence_count": len(evidence),
            "finding_count": len(findings),
            "diagram_count": len(diagrams),
            "playbook_required_evidence_types": playbook.required_evidence_types,
            "playbook_optional_evidence_types": playbook.optional_evidence_types,
        }
        return ClaimGraph(
            case_id=case_id,
            report_version=report_version,
            renderer_family=renderer_family,
            claims=claims,
            alternative_hypotheses=alternatives,
            financial_impact=financial,
            global_boundaries=boundaries,
            metadata=metadata,
        )

    def _address_boundary_claims(self, case, evidence: list, evidence_ids: list[str]) -> list[ReportClaim]:
        refs = self._refs(evidence)
        return [
            ReportClaim(
                claim_id="C-SCOPE-001",
                section="当前可确认范围",
                claim_type="boundary",
                text=f"输入地址 {case.seed_value} 已被记录为线索，但当前没有形成交易范围。",
                confidence="partial",
                support_evidence_ids=evidence_ids[:8],
                evidence_refs=refs[:8],
                reasoning="地址 seed 需要 Explorer txlist 或用户补充 seed transaction；孤立地址不能推导攻击路径。",
                falsification="配置 Explorer API key 或补充 seed transaction 后重新运行 discovery。",
            )
        ]

    def _external_event_claims(self, case, evidence: list, evidence_ids: list[str]) -> list[ReportClaim]:
        refs = self._refs(evidence)
        incident = self._first_evidence(evidence, "external_incident_seed") or self._first_evidence(evidence, "defillama_hack_record")
        incident_text = f"外部事件线索 `{case.seed_value}` 已登记，但当前没有 seed transaction 或链上交易范围。"
        if incident and isinstance(incident.decoded, dict):
            decoded = incident.decoded or {}
            name = decoded.get("name") or decoded.get("title") or case.title
            technique = decoded.get("technique")
            amount = decoded.get("amount")
            incident_text = f"DefiLlama / 外部事件线索显示 `{name}` 被记录为安全事件"
            if technique:
                incident_text += f"，技术标签为 `{technique}`"
            if amount is not None:
                incident_text += f"，损失口径约为 `{amount}` USD"
            incident_text += "；这些信息仍属于外部情报，尚未被本地链上 evidence 复核。"
        return [
            ReportClaim(
                claim_id="C-ALERT-001",
                section="当前可确认范围",
                claim_type="boundary",
                text=incident_text,
                confidence="partial",
                support_evidence_ids=evidence_ids[:8],
                evidence_refs=refs[:8],
                reasoning="外部事件入口只是一条情报线索。正式根因分析需要核心交易、交易收据、调用跟踪、事件日志或资金流证据。",
                falsification="补充 seed transaction / txlist / 官方 postmortem 后重新运行 workflow。",
            ),
            ReportClaim(
                claim_id="C-ALERT-002",
                section="当前不能确认的内容",
                claim_type="boundary",
                text="当前不能确认攻击路径、漏洞根因、攻击者地址、受害合约或本地复算损失。",
                confidence="high",
                support_evidence_ids=evidence_ids[:8],
                evidence_refs=refs[:8],
                reasoning="本报告版本还没有建立交易范围。",
            ),
        ]

    def _transaction_preanalysis_claims(self, case, transactions: list, evidence: list) -> list[ReportClaim]:
        claims: list[ReportClaim] = []
        tx_scope = self._first_evidence(evidence, "transaction_in_case_scope")
        transfer = self._first_evidence(evidence, "native_value_transfer")
        receipt = self._first_evidence(evidence, "evm_receipt_events_normalized")
        support = [item.id for item in [tx_scope, transfer, receipt] if item is not None]
        claims.append(
            ReportClaim(
                claim_id="C-TX-001",
                section="交易基本信息",
                claim_type="fact",
                text=f"Seed {case.seed_value} 是一笔链上交易，当前报告只确认交易事实。",
                confidence="high" if tx_scope else "partial",
                support_evidence_ids=support[:8],
                evidence_refs=self._refs([item for item in [tx_scope, transfer, receipt] if item is not None]),
                reasoning="交易范围来自 tx metadata、receipt 或 full block fallback。",
                metadata={"tx_hash": case.seed_value, "transaction_count": len(transactions)},
            )
        )
        if transfer:
            decoded = transfer.decoded or {}
            claims.append(
                ReportClaim(
                    claim_id="C-TX-002",
                    section="调用与资金移动",
                    claim_type="fact",
                    text=f"交易内确认原生资产移动：{decoded.get('amount') or decoded.get('amount_raw')}，从 {decoded.get('from')} 转至 {decoded.get('to')}。",
                    confidence="high",
                    support_evidence_ids=[transfer.id],
                    evidence_refs=self._refs([transfer]),
                    reasoning="原生资产移动来自交易 value 或余额变化证据。",
                    metadata=decoded,
                )
            )
        claims.append(
            ReportClaim(
                claim_id="C-TX-003",
                section="不能确认的攻击结论",
                claim_type="boundary",
                text="当前 evidence 不能证明攻击、漏洞根因或协议损失。",
                confidence="high",
                support_evidence_ids=support[:8],
                evidence_refs=self._refs([item for item in [tx_scope, transfer, receipt] if item is not None]),
                reasoning="没有 calldata、关键事件日志、source/trace 异常或 high-risk finding 支撑攻击 RCA。",
                falsification="补充 trace/source/protocol event 或外部事件证据后重新生成报告。",
            )
        )
        return claims

    def _full_rca_claims(self, case, transactions: list, timeline: list[dict], evidence: list, findings: list, renderer_family: str, invariants: list[str]) -> list[ReportClaim]:
        claims: list[ReportClaim] = []
        tx_evidence_ids = [item.id for item in evidence if item.source_type == "tx_metadata"][:8]
        if transactions:
            claims.append(
                ReportClaim(
                    claim_id="C-SCOPE-001",
                    section="事件范围",
                    claim_type="fact",
                    text=f"本报告范围包含 {len(transactions)} 笔交易，核心入口为 {case.seed_value}。",
                    confidence="high" if tx_evidence_ids else "medium",
                    support_evidence_ids=tx_evidence_ids,
                    evidence_refs=self._refs([item for item in evidence if item.id in tx_evidence_ids]),
                    reasoning="交易范围来自案例交易范围和交易元数据证据。",
                    metadata={"transaction_count": len(transactions), "timeline_count": len(timeline)},
                )
            )
        root_finding = self._root_finding(findings)
        root_ids = list(root_finding.evidence_ids) if root_finding else self._deterministic_evidence_ids(evidence)[:5]
        if root_finding or case.root_cause_one_liner:
            claims.append(
                ReportClaim(
                    claim_id="C-ROOT-001",
                    section="根因分析",
                    claim_type="root_cause",
                    text=case.root_cause_one_liner or root_finding.claim,
                    confidence=self._confidence(root_finding.confidence if root_finding else case.confidence),
                    support_evidence_ids=root_ids,
                    evidence_refs=self._refs([item for item in evidence if item.id in root_ids]),
                    reasoning=self._root_reasoning(root_finding, renderer_family, invariants),
                    falsification=(
                        self._localized_text(root_finding.falsification)
                        if root_finding
                        else "如果调用跟踪或源码证据与当前漏洞路径相矛盾，应下调该根因结论。"
                    ),
                    metadata={
                        "finding_id": root_finding.id if root_finding else None,
                        "renderer_family": renderer_family,
                        "violated_invariant": invariants[0] if invariants else "Report conclusions must match evidence strength.",
                    },
                )
            )
        for index, finding in enumerate(findings[:8], start=1):
            claim_type = "root_cause" if finding.finding_type in {"root_cause", "contract_bug"} and not any(c.claim_id == "C-ROOT-001" for c in claims) else "inference"
            claims.append(
                ReportClaim(
                    claim_id=f"C-FINDING-{index:03d}",
                    section="结论与证据等级",
                    claim_type=claim_type,
                    text=f"{self._localized_text(finding.title)}：{self._localized_text(finding.claim)}",
                    confidence=self._confidence(finding.confidence),
                    support_evidence_ids=list(finding.evidence_ids),
                    evidence_refs=self._refs([item for item in evidence if item.id in set(finding.evidence_ids)]),
                    reasoning=self._localized_text(finding.rationale) if finding.rationale else "该结论来自结构化 worker 输出，并已绑定证据。",
                    falsification=self._localized_text(finding.falsification),
                    metadata={"finding_type": finding.finding_type, "severity": finding.severity, "reviewer_status": finding.reviewer_status},
                )
            )
        return claims

    def _remediation_claims(self, templates: list[str], existing_claims: list[ReportClaim]) -> list[ReportClaim]:
        root = next((claim for claim in existing_claims if claim.claim_type == "root_cause"), None)
        if root is None:
            return []
        return [
            ReportClaim(
                claim_id=f"C-REMEDIATION-{index:03d}",
                section="修复建议",
                claim_type="remediation",
                text=template,
                confidence="medium",
                support_evidence_ids=root.support_evidence_ids,
                evidence_refs=root.evidence_refs,
                reasoning="修复建议绑定到已接受的根因结论和对应分析剧本。",
                metadata={"root_cause_claim_id": root.claim_id},
            )
            for index, template in enumerate(templates[:5], start=1)
        ]

    def _transaction_financial_items(self, evidence: list) -> list[FinancialImpactItem]:
        transfer = self._first_evidence(evidence, "native_value_transfer")
        if not transfer:
            return []
        decoded = transfer.decoded or {}
        return [
            FinancialImpactItem(
                item_id="FI-001",
                category="unpriced_movement",
                asset=str(decoded.get("asset") or "native"),
                amount_raw=str(decoded.get("amount_raw") or decoded.get("amount") or ""),
                amount_display=str(decoded.get("amount") or decoded.get("amount_raw") or ""),
                support_evidence_ids=[transfer.id],
                confidence="high",
                notes="没有攻击特异性证据时，原生资产移动不能等同于已确认协议损失。",
            )
        ]

    def _attack_financial_items(self, case, evidence: list) -> list[FinancialImpactItem]:
        items: list[FinancialImpactItem] = []
        loss_evidence = [item for item in evidence if "loss" in item.claim_key.lower() or "fund" in item.claim_key.lower() or item.source_type == "balance_diff"]
        if case.loss_usd is not None:
            items.append(
                FinancialImpactItem(
                    item_id="FI-001",
                    category="probable_loss",
                    asset="USD",
                    usd_value=f"{float(case.loss_usd):.2f}",
                    price_source=None,
                    support_evidence_ids=[item.id for item in loss_evidence[:6]],
                    confidence="medium" if loss_evidence else "partial",
                    notes="如果证据中没有价格来源，case 级美元损失只作为推定损失处理。",
                )
            )
        for index, item in enumerate(loss_evidence[:6], start=len(items) + 1):
            decoded = item.decoded or {}
            for edge in (decoded.get("fund_flow_edges") or decoded.get("flows") or [decoded])[:5]:
                if not isinstance(edge, dict):
                    continue
                amount = edge.get("amount") or edge.get("amount_raw")
                asset = edge.get("asset") or edge.get("token") or "unknown"
                if amount:
                    items.append(
                        FinancialImpactItem(
                            item_id=f"FI-{index:03d}",
                            category="unpriced_movement",
                            asset=str(asset),
                            amount_raw=str(edge.get("amount_raw") or amount),
                            amount_display=str(amount),
                            support_evidence_ids=[item.id],
                            confidence=self._confidence(edge.get("confidence") or item.confidence),
                            notes="保留代币数量层面的资金移动，但不把它写成已完成美元估值。",
                        )
                    )
                    break
        if not items:
            items.append(
                FinancialImpactItem(
                    item_id="FI-BOUNDARY-001",
                    category="out_of_scope",
                    asset="unknown",
                    confidence="partial",
                    notes="本报告版本没有采集到确定性损失或价格证据。",
                )
            )
        return items

    def _alternative_hypotheses(self, report_type: str, renderer_family: str, findings: list, evidence_by_id: dict) -> list[AlternativeHypothesis]:
        if report_type != "attack_rca":
            return []
        playbook = get_playbook(renderer_family)
        finding_ids = [evidence_id for finding in findings for evidence_id in finding.evidence_ids]
        alternatives: list[AlternativeHypothesis] = []
        for index, name in enumerate(playbook.common_alternative_hypotheses[:6], start=1):
            status = "accepted" if self._matches_renderer(name, renderer_family) else "insufficient_evidence"
            alternatives.append(
                AlternativeHypothesis(
                    hypothesis_id=f"H-{index:03d}",
                    name=name,
                    status=status,
                    support_evidence_ids=finding_ids[:5] if status == "accepted" else [],
                    contradicting_evidence_ids=[],
                    rationale=(
                        "当前分析类型与已有 finding 和 evidence 一致。"
                        if status == "accepted"
                        else "当前结构化证据不足以把该假设确立为主要解释。"
                    ),
                    confidence="medium",
                )
            )
        return alternatives

    def _global_boundaries(self, case, evidence: list, jobs: list, report_type: str) -> list[str]:
        boundaries: list[str] = []
        if report_type == "address_boundary":
            boundaries.append("地址入口尚未形成交易范围。")
        if report_type == "external_event_preanalysis":
            boundaries.append("当前只有外部事件线索，本地尚未形成交易范围。")
        if report_type == "transaction_preanalysis":
            boundaries.append("当前交易证据不能证明漏洞根因或协议损失。")
        if any(item.claim_key == "address_discovery_explorer_missing" for item in evidence):
            boundaries.append("区块浏览器交易列表或源码补充能力不可用。")
        if any("TxAnalyzer root not found" in str(job.error or job.output) for job in jobs):
            boundaries.append("当前环境无法获得 TxAnalyzer 工件。")
        return boundaries

    def _report_type(self, case, transactions: list, evidence: list, findings: list) -> str:
        if case.seed_type == "address" and (not transactions or any(item.claim_key == "address_discovery_explorer_missing" for item in evidence)):
            return "address_boundary"
        if case.seed_type == "alert" and not transactions:
            return "external_event_preanalysis"
        if self._is_transaction_observation(case, evidence, findings):
            return "transaction_preanalysis"
        return "attack_rca"

    def _is_transaction_observation(self, case, evidence: list, findings: list) -> bool:
        if case.seed_type != "transaction":
            return False
        if case.attack_type:
            return False
        if case.severity not in {"info", "unknown", "low"}:
            return False
        if any(item.severity in {"medium", "high", "critical"} for item in findings):
            return False
        special = {"revert_receipt_flow_summary", "bunni_case_profile", "scallop_reward_profile", "purrlend_megaeth_case_profile", "external_incident_seed"}
        return not any(item.claim_key in special or item.source_type in {"trace_call", "source_line", "signature", "state_call"} for item in evidence)

    def _root_finding(self, findings: list):
        ranked = [item for item in findings if item.severity in {"critical", "high", "medium"}]
        return ranked[0] if ranked else (findings[0] if findings else None)

    def _root_reasoning(self, finding, renderer_family: str, invariants: list[str]) -> str:
        invariant = invariants[0] if invariants else "协议不变量根据当前分析类型推断。"
        rationale = self._localized_text(finding.rationale) if finding else "根因来自 case 级 RCA worker 输出。"
        invariant = str(invariant).rstrip("。.")
        rationale = str(rationale).rstrip()
        return f"被违反的不变量：{invariant}。脆弱路径或缺失校验：{rationale}"

    def _deterministic_evidence_ids(self, evidence: list) -> list[str]:
        return [item.id for item in evidence if item.source_type in DETERMINISTIC_EVIDENCE_TYPES]

    def _first_evidence(self, evidence: list, claim_key: str):
        return next((item for item in evidence if item.claim_key == claim_key), None)

    def _refs(self, evidence: list) -> list[EvidenceRef]:
        return [
            EvidenceRef(
                evidence_id=item.id,
                source_type=item.source_type,
                producer=item.producer,
                claim_key=item.claim_key,
                raw_path=item.raw_path,
            )
            for item in evidence
        ]

    def _confidence(self, value: Any) -> str:
        text = str(value or "partial").lower()
        return text if text in {"high", "medium", "low", "partial"} else "partial"

    def _matches_renderer(self, name: str, renderer_family: str) -> bool:
        normalized = name.replace(" ", "_").replace("-", "_").lower()
        family = renderer_family.lower()
        return any(part and part in family for part in normalized.split("_"))

    def _localized_text(self, value: Any) -> str:
        text = str(value or "")
        replacements = {
            "Asset movement evidence observed": "已观察到资产移动证据",
            "Detected ": "检测到 ",
            " native/token transfer evidence item(s).": " 条原生资产或代币转移证据。",
            "Transfer logs and native value movement are deterministic fund-flow evidence, but they do not prove an exploit, root cause, or loss by themselves.": "Transfer 日志和原生资产移动属于确定性资金流证据，但单独不能证明存在攻击、漏洞根因或协议损失。",
            "Correlate the transfer with exploit-specific receipt logs, permission changes, source code, trace, price impact, or external incident evidence before treating it as a security finding.": "在把资金移动作为安全结论前，需要把它与攻击特异性的 receipt 日志、权限变化、源码、调用跟踪、价格影响或外部事件证据关联起来。",
            "The seed transaction and token transfer confirm the Ethereum release. External technical analyses identify the violated invariant as cross-chain burn/release consistency under a 1-of-1 DVN trust model.": "核心交易和代币转移确认了 Ethereum 侧资产释放。外部技术分析把被违反的不变量定位为 1-of-1 验证网络信任模型下的跨链销毁/释放一致性。",
            "The report must not be publishable until deterministic evidence exists.": "在缺少确定性证据前，报告不能发布为确定性结论。",
            "This high finding is intentionally backed by weak evidence.": "该高危结论当前只绑定弱证据，用于验证质量门禁。",
            "Root cause is derived from case-level RCA worker output.": "根因来自 case 级 RCA worker 输出。",
            "Finding generated from structured worker output and bound evidence.": "该结论来自结构化 worker 输出，并已绑定证据。",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        return text

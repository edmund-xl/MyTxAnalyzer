from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.object_store import ObjectStore
from app.models.schemas import FindingCreate, WorkerResult
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService
from app.services.job_service import JobService


class RCAAgentWorker:
    name = "rca_agent_worker"

    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def run(self, case_id: str) -> WorkerResult:
        job_service = JobService(self.db)
        job = job_service.start(case_id, self.name, {})
        try:
            case = CaseService(self.db).get_case(case_id)
            evidence = EvidenceService(self.db).list_for_case(case_id)
            findings = FindingService(self.db).list_for_case(case_id)
            if not findings and evidence:
                deterministic = [item.id for item in evidence if item.source_type != "agent_inference"]
                if self._address_seed_without_scope(case, evidence):
                    FindingService(self.db).create_finding(
                        case_id,
                        FindingCreate(
                            title="地址入口未形成交易范围",
                            finding_type="evidence_boundary",
                            severity="info",
                            confidence="partial",
                            claim="地址入口已记录，但本 case 还没有采集到交易列表、交易收据日志或资金流证据。",
                            rationale="地址型根因分析需要区块浏览器交易列表 API key，或至少一笔具体的核心交易。当前公共 RPC fallback 可以验证网络，但不能枚举地址历史。",
                            falsification="补充核心交易哈希，或配置该网络的区块浏览器 API key，然后重新运行 discovery 和 TxAnalyzer。",
                            evidence_ids=deterministic[:5],
                            requires_reviewer=True,
                            created_by=self.name,
                        ),
                    )
                else:
                    FindingService(self.db).create_finding(
                        case_id,
                        FindingCreate(
                            title="基于证据的根因草稿需要人工复核",
                            finding_type="data_quality",
                            severity="info",
                            confidence="medium",
                            claim="系统已采集 evidence，但没有自动识别出专门的高风险根因结论。",
                            rationale="当只有通用证据可用时，本地 RCA worker 会避免输出缺少支撑的强结论。",
                            falsification="补齐工件后重新运行 ACL、Safe 和 FundFlow 模块，以提高结论置信度。",
                            evidence_ids=deterministic[:5],
                            requires_reviewer=True,
                            created_by=self.name,
                        ),
                    )
            refreshed_findings = FindingService(self.db).list_for_case(case_id)
            root = self._root_cause(refreshed_findings)
            case.root_cause_one_liner = root
            case.attack_type = self._attack_type(refreshed_findings)
            case.severity = self._severity(refreshed_findings)
            case.confidence = self._confidence(refreshed_findings)
            self.db.add(case)
            self.db.commit()
            output = {
                "root_cause_one_liner": root,
                "attack_type": case.attack_type,
                "severity": case.severity,
                "confidence": case.confidence,
                "finding_count": len(refreshed_findings),
                "blockers": [],
                "open_questions": [] if evidence else ["No evidence rows available"],
            }
            content = json.dumps(output, indent=2, ensure_ascii=False).encode("utf-8")
            artifact_uri = self.object_store.put_bytes(content, f"cases/{case_id}/agent/rca_agent_output.json", "application/json")
            EvidenceService(self.db).create_artifact(case_id, self.name, "agent_output", artifact_uri, self.object_store.sha256_bytes(content), len(content))
            job_service.finish(job, "success", output=output)
            return WorkerResult(case_id=case_id, worker_name=self.name, status="success", summary=output, artifacts=[artifact_uri])
        except Exception as exc:
            job_service.finish(job, "failed", error=str(exc))
            return WorkerResult(case_id=case_id, worker_name=self.name, status="failed", summary={}, error=str(exc))

    def _root_cause(self, findings) -> str:
        if any(f.finding_type == "evidence_boundary" for f in findings):
            return "地址入口未形成交易范围；当前证据不能建立攻击根因。"
        if any(f.finding_type == "revert_collateralized_position_solvency_check_missing" for f in findings):
            return "Revert Finance 证据显示，质押/管理路径缺少偿付约束，导致带债 LP NFT 的底层流动性仍可被移出。"
        if any(f.finding_type == "scallop_deprecated_reward_contract" for f in findings):
            return "Scallop 事件证据指向废弃 Sui 奖励合约路径，该路径允许异常领取 sSUI spool 奖励。"
        if any(f.finding_type == "purrlend_unbacked_mint_control_failure" for f in findings):
            return "Purrlend MegaETH 证据显示，未支持铸造额度与借款控制失效，使攻击者能够提取真实资产。"
        if any(f.finding_type == "access_control" for f in findings):
            return "证据显示访问控制授权路径与事件核心相关；发布前需要 reviewer 确认。"
        if any(f.finding_type == "multisig" for f in findings):
            return "证据显示多签执行路径相关；签名者归因需要 reviewer 验证。"
        if any(f.finding_type == "fund_flow" for f in findings):
            return "证据目前只确认资产移动；如果没有权限、源码、调用跟踪、价格影响或事件关联证据，不能建立攻击根因。"
        return "现有证据尚未建立高置信度根因。"

    def _attack_type(self, findings) -> str | None:
        if any(f.finding_type == "evidence_boundary" for f in findings):
            return "address_scope_boundary"
        if any(f.finding_type == "revert_collateralized_position_solvency_check_missing" for f in findings):
            return "collateralized_lp_position_solvency_check_missing"
        if any(f.finding_type == "scallop_deprecated_reward_contract" for f in findings):
            return "deprecated_reward_contract_reward_accounting"
        if any(f.finding_type == "purrlend_unbacked_mint_control_failure" for f in findings):
            return "unbacked_mint_borrow_control_failure"
        if any(f.finding_type == "access_control" for f in findings):
            return "access_control_abuse"
        if any(f.finding_type == "multisig" for f in findings):
            return "multisig_authorization"
        if any(f.finding_type == "fund_flow" and f.severity in {"medium", "high", "critical"} for f in findings):
            return "fund_flow"
        return None

    def _severity(self, findings) -> str:
        order = ["critical", "high", "medium", "low", "info", "unknown"]
        severities = [f.severity for f in findings]
        for severity in order:
            if severity in severities:
                return severity
        return "unknown"

    def _confidence(self, findings) -> str:
        order = ["high", "medium", "partial", "low"]
        confidences = [f.confidence for f in findings]
        for confidence in order:
            if confidence in confidences:
                return confidence
        return "low"

    def _address_seed_without_scope(self, case, evidence) -> bool:
        return case.seed_type == "address" and any(item.claim_key == "address_discovery_explorer_missing" for item in evidence)

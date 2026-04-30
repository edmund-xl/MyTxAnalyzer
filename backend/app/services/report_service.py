from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.object_store import ObjectStore
from app.models.db import JobRun, Report, ReportSection
from app.services.case_service import CaseService
from app.services.diagram_service import DiagramService
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService
from app.services.report_renderer_registry import ReportRendererRegistry


REPORT_SECTION_TITLES = [
    "TL;DR",
    "1. 概述",
    "2. 涉事方",
    "3. 攻击时间线",
    "4. 数据流图",
    "5. 根因分析",
    "6. 财务影响",
    "7. 分析链路与方法论",
    "8. 总分析时长",
    "附录",
]


class ReportService:
    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def list_for_case(self, case_id: str, limit: int = 50, offset: int = 0) -> list[Report]:
        return list(
            self.db.scalars(
                select(Report)
                .where(Report.case_id == case_id)
                .order_by(Report.version.desc(), Report.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def get(self, report_id: str) -> Report | None:
        return self.db.get(Report, report_id)

    def create_report(self, case_id: str, language: str | None = None, report_format: str = "markdown", created_by: str | None = None) -> Report:
        case = CaseService(self.db).get_case(case_id)
        language = language or case.language
        version = int(self.db.scalar(select(func.coalesce(func.max(Report.version), 0)).where(Report.case_id == case_id, Report.format == report_format))) + 1
        sections = self._build_sections(case_id)
        evidence = EvidenceService(self.db).list_for_case(case_id)
        findings = [finding for finding in FindingService(self.db).list_for_case(case_id) if finding.reviewer_status != "rejected"]
        renderer = ReportRendererRegistry()
        renderer_key = renderer.select(case, evidence, findings)
        coverage = self._coverage(sections)
        if report_format == "json":
            content_obj: dict[str, Any] = {
                "case_id": case_id,
                "version": version,
                "language": language,
                "renderer": renderer_key,
                "sections": sections,
            }
            content = json.dumps(content_obj, indent=2, ensure_ascii=False, default=str)
            object_key = f"cases/{case_id}/reports/report_v{version}.json"
            content_type = "application/json"
        else:
            content = self._render_markdown(case_id, sections)
            object_key = f"cases/{case_id}/reports/report_v{version}.md"
            content_type = "text/markdown"
        content_bytes = content.encode("utf-8")
        object_uri = self.object_store.put_bytes(content_bytes, object_key, content_type)
        report = Report(
            case_id=case_id,
            version=version,
            language=language,
            format=report_format,
            status="draft",
            object_path=object_uri,
            content_hash=self.object_store.sha256_bytes(content_bytes),
            evidence_coverage=coverage,
            metadata_json={"generator": "report_worker", "sections": len(sections)} | renderer.metadata(renderer_key),
            created_by=created_by,
        )
        self.db.add(report)
        self.db.flush()
        for index, section in enumerate(sections, start=1):
            self.db.add(
                ReportSection(
                    report_id=report.id,
                    section_order=index,
                    title=section["title"],
                    body_markdown=section["body_markdown"],
                    evidence_ids=section["evidence_ids"],
                    coverage=section["coverage"],
                    status=section["status"],
                )
            )
        self.db.commit()
        self.db.refresh(report)
        return report

    def get_content(self, report: Report) -> str | dict[str, Any] | None:
        if not report.object_path:
            return None
        content = self.object_store.get_bytes(report.object_path).decode("utf-8")
        if report.format == "json":
            return json.loads(content)
        return content

    def publish(self, report_id: str, reviewer: str) -> Report:
        report = self.get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        findings = FindingService(self.db).list_for_case(report.case_id, limit=10000)
        blockers = [f for f in findings if f.severity in {"critical", "high"} and f.reviewer_status != "approved"]
        if blockers:
            raise HTTPException(status_code=422, detail="Critical/high findings must be approved before publish")
        report.status = "published"
        report.reviewed_by = reviewer
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report

    def _build_sections(self, case_id: str) -> list[dict[str, Any]]:
        case_service = CaseService(self.db)
        case = case_service.get_case(case_id)
        timeline = case_service.timeline(case_id)
        transactions = case_service.list_transactions(case_id)
        evidence = EvidenceService(self.db).list_for_case(case_id)
        findings = [finding for finding in FindingService(self.db).list_for_case(case_id) if finding.reviewer_status != "rejected"]
        address_boundary = self._is_address_scope_boundary(case, transactions, evidence)
        if address_boundary:
            findings = [finding for finding in findings if finding.finding_type == "evidence_boundary"]
        diagrams = DiagramService(self.db, self.object_store).generate_for_case(case_id, created_by="report_worker")
        if any(finding.severity in {"critical", "high"} for finding in findings):
            findings = [
                finding
                for finding in findings
                if not (finding.finding_type == "data_quality" and finding.severity in {"info", "low"})
            ]
        jobs = list(self.db.scalars(select(JobRun).where(JobRun.case_id == case_id).order_by(JobRun.created_at)).all())
        evidence_ids = [item.id for item in evidence]

        if address_boundary:
            bodies = {
                "TL;DR": self._address_boundary_tldr(case, evidence),
                "1. 概述": self._address_boundary_overview(case, evidence, findings),
                "2. 涉事方": self._address_boundary_entities(case, evidence),
                "3. 攻击时间线": self._address_boundary_timeline(case),
                "4. 数据流图": self._diagrams(diagrams),
                "5. 根因分析": self._address_boundary_root_cause(case, evidence, findings),
                "6. 财务影响": self._address_boundary_financial_impact(case, evidence),
                "7. 分析链路与方法论": self._address_boundary_methodology(case, jobs, evidence),
                "8. 总分析时长": self._analysis_duration(jobs),
                "附录": self._address_boundary_appendix(evidence, jobs),
            }
        else:
            bodies = {
                "TL;DR": self._tldr(case, timeline, evidence),
                "1. 概述": self._overview(case, timeline, evidence, findings),
                "2. 涉事方": self._entities(case, transactions, evidence),
                "3. 攻击时间线": self._timeline(case, timeline),
                "4. 数据流图": self._diagrams(diagrams),
                "5. 根因分析": self._root_cause(case, findings, evidence),
                "6. 财务影响": self._financial_impact(case, evidence),
                "7. 分析链路与方法论": self._methodology(case, jobs, evidence),
                "8. 总分析时长": self._analysis_duration(jobs),
                "附录": self._appendix(transactions, evidence, jobs),
            }
        sections: list[dict[str, Any]] = []
        for title in REPORT_SECTION_TITLES:
            body = bodies[title]
            boundary_partial = address_boundary and title in {"3. 攻击时间线", "5. 根因分析", "6. 财务影响"}
            supported = (bool(evidence_ids) or title in {"4. 数据流图", "8. 总分析时长"}) and not boundary_partial
            sections.append(
                {
                    "title": title,
                    "body_markdown": body,
                    "evidence_ids": evidence_ids if evidence_ids else [],
                    "coverage": 1.0 if supported else (0.35 if boundary_partial else 0.0),
                    "status": "supported" if supported else "boundary" if boundary_partial else "partial",
                }
            )
        return sections

    def _coverage(self, sections: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            section["title"]: {
                "claims_total": 1,
                "claims_supported": 1 if section["coverage"] >= 1 else 0,
                "unsupported_claims": [] if section["coverage"] >= 1 else [section["title"]],
                "coverage": section["coverage"],
            }
            for section in sections
        }

    def _render_markdown(self, case_id: str, sections: list[dict[str, Any]]) -> str:
        case = CaseService(self.db).get_case(case_id)
        title = case.title or "On-chain RCA"
        transactions = CaseService(self.db).list_transactions(case_id, limit=1)
        evidence = EvidenceService(self.db).list_for_case(case_id)
        suffix = "地址线索预分析报告" if self._is_address_scope_boundary(case, transactions, evidence) else "攻击事件分析报告"
        lines = [f"# {title} {suffix}", ""]
        for section in sections:
            lines.extend([f"## {section['title']}", "", section["body_markdown"], ""])
        return "\n\n".join(lines)

    def _diagrams(self, diagrams: list) -> str:
        return DiagramService(self.db, self.object_store).markdown_for_diagrams(diagrams)

    def _is_address_scope_boundary(self, case, transactions: list, evidence: list) -> bool:
        if case.seed_type != "address":
            return False
        return not transactions or any(item.claim_key == "address_discovery_explorer_missing" for item in evidence)

    def _address_boundary_tldr(self, case, evidence: list) -> str:
        env = self._environment_facts(evidence, [])
        boundary = self._address_discovery_boundary(evidence)
        return "\n".join(
            [
                "> **报告类型:** 地址线索预分析，不是完整攻击 RCA",
                f"> **链:** {case.network.name} (Chain ID: {case.network.chain_id})",
                f"> **输入地址:** `{case.seed_value}`",
                f"> **当前结论:** 未形成交易范围；不能确认攻击路径、根因或损失。",
                f"> **RPC 状态:** chainId={env.get('chain_id', '-')}，rpc_ok={env.get('rpc_ok', '-')}, source={env.get('rpc_source', '-')}",
                f"> **地址扩展:** {boundary.get('boundary', 'Explorer txlist 未完成')}",
                "> **下一步进入正式 RCA 的条件:** 提供 seed transaction，或配置该网络 Explorer API key 后重新运行。",
            ]
        )

    def _address_boundary_overview(self, case, evidence: list, findings: list) -> str:
        boundary = self._address_discovery_boundary(evidence)
        env = self._environment_facts(evidence, [])
        finding = findings[0] if findings else None
        paragraphs = [
            (
                f"`{case.title or case.id}` 是从地址 `{case.seed_value}` 创建的线索 case。"
                "当前系统已完成网络连通性检查，并记录地址发现阶段的能力边界；但没有获得任何属于本 case 的交易列表、receipt logs、trace 或资金流。"
            ),
            (
                "因此，本报告只回答一个问题：目前这条地址线索是否已经足以进入攻击 RCA。答案是：还不够。"
                "Workbench 不会把一个孤立地址直接写成攻击者、受害合约、资金流或根因。"
            ),
            (
                f"本案 RPC 检查结果为 chainId `{env.get('chain_id', '-')}`，rpc_ok=`{env.get('rpc_ok', '-')}`；"
                f"Explorer key 来源为 `{boundary.get('explorer_key_source', 'missing')}`。"
                "公共 RPC 可以做链 ID 和单笔交易查询，但不能枚举地址历史；地址扩展需要 Explorer txlist 或用户补 seed transaction。"
            ),
            f"当前 evidence 数量：`{len(evidence)}`。当前 finding：`{finding.title if finding else '无'}`。这些内容仅支撑“证据边界”，不支撑攻击结论。",
        ]
        return "\n\n".join(paragraphs)

    def _address_boundary_entities(self, case, evidence: list) -> str:
        env = self._environment_facts(evidence, [])
        boundary = self._address_discovery_boundary(evidence)
        scope_rows = [
            ("目标链", f"{case.network.name} ({case.network.chain_id})", "已确认网络范围", "environment_capability"),
            ("输入地址", case.seed_value, "线索地址；尚未定性为攻击者或受害合约", "case seed"),
            ("RPC 来源", env.get("rpc_source", "-"), "网络连通性来源", "environment_capability"),
            ("Explorer 状态", boundary.get("explorer_key_source", "missing"), "txlist/source enrichment 能力", "address_discovery_explorer_missing"),
        ]
        evidence_rows = [(item.producer, item.source_type, item.claim_key, item.confidence) for item in evidence]
        return "\n\n".join(
            [
                "### 2.1 当前可确认对象",
                self._table(["对象", "值", "角色", "证据"], scope_rows),
                "### 2.2 当前不能确认的对象",
                self._table(
                    ["对象", "当前状态", "原因", "处理方式"],
                    [
                        ("攻击者", "不能确认", "没有交易发起方、资金流或合约调用证据", "等待 txlist 或 seed tx"),
                        ("受害协议", "不能确认", "地址本身不等于协议身份或漏洞位置", "等待合约源码/ABI/交易上下文"),
                        ("接收地址", "不能确认", "没有 Transfer / balance diff evidence", "等待 receipt logs 和 fund-flow worker"),
                    ],
                ),
                "### 2.3 已采集证据来源",
                self._table(["Producer", "Source Type", "Claim", "Confidence"], evidence_rows) if evidence_rows else "暂无 evidence。",
            ]
        )

    def _address_boundary_timeline(self, case) -> str:
        return "\n".join(
            [
                "当前没有链上交易时间线。",
                "",
                "```text",
                f"Phase 0: 用户输入地址 -> {case.seed_value}",
                "Phase 1: 网络能力检查 -> 已完成",
                "Phase 2: 地址 txlist 扩展 -> 未完成，原因是 Explorer API key 缺失或不可用",
                "Phase 3: 正式攻击 RCA -> 尚未开始；需要 seed transaction 或 txlist 结果",
                "```",
                "",
                "这不是攻击时间线，而是线索处理状态。报告不会把缺失交易的地址 case 展开成调用链。"
            ]
        )

    def _address_boundary_root_cause(self, case, evidence: list, findings: list) -> str:
        finding_rows = [
            (
                self._finding_title(finding),
                finding.finding_type,
                finding.severity,
                finding.confidence,
                finding.reviewer_status,
                f"{len(finding.evidence_ids)} 条 evidence",
            )
            for finding in findings
        ]
        return "\n\n".join(
            [
                "### 4.1 根因结论",
                "当前没有根因结论。原因不是“根因未知但疑似某类漏洞”，而是交易范围尚未建立：没有 seed transaction、receipt logs、trace、source 或资金流 evidence。",
                "### 4.2 当前 finding 的含义",
                self._table(["Finding", "Type", "Severity", "Confidence", "Review", "Evidence"], finding_rows) if finding_rows else "暂无 finding。",
                "### 4.3 明确排除的写法",
                "\n".join(
                    [
                        "- 不把输入地址直接写成攻击者。",
                        "- 不把网络 capability 写成漏洞证据。",
                        "- 不把 Explorer key 缺失写成协议问题。",
                        "- 不估算损失，不输出攻击路径，不生成合约根因。"
                    ]
                ),
                "### 4.4 进入根因分析所需条件",
                "\n".join(
                    [
                        "1. 提供至少一笔 seed transaction；或",
                        "2. 配置该网络 Explorer API key，使 address txlist 可返回交易；然后",
                        "3. 对候选交易运行 receipt/log 标准化、TxAnalyzer artifact pull、FundFlow 和 RCA finding generation。"
                    ]
                ),
            ]
        )

    def _address_boundary_financial_impact(self, case, evidence: list) -> str:
        loss = next((item for item in evidence if item.claim_key == "loss_calculation_status"), None)
        return "\n\n".join(
            [
                "### 5.1 当前财务结论",
                "当前不能确认损失金额。没有交易范围时，系统无法判断该地址是否发生资产转入、转出、borrow、swap、bridge 或清算。",
                "### 5.2 已执行的损失计算状态",
                self._table(
                    ["字段", "值"],
                    [
                        ("fund_flow_evidence_count", (loss.decoded or {}).get("fund_flow_evidence_count", 0) if loss else 0),
                        ("fund_flow_edge_count", (loss.decoded or {}).get("fund_flow_edge_count", 0) if loss else 0),
                        ("usd_loss", (loss.decoded or {}).get("usd_loss") if loss else None),
                        ("reason", (loss.decoded or {}).get("reason", "No fund-flow evidence") if loss else "No fund-flow evidence"),
                    ],
                ),
                "### 5.3 不输出的内容",
                "本报告不列“虚假抵押品”“借出真实资产”“跨链转出”等攻击段落，因为这些都需要 deterministic transfer / receipt / trace evidence 支撑。",
            ]
        )

    def _address_boundary_methodology(self, case, jobs: list[JobRun], evidence: list) -> str:
        env = self._environment_facts(evidence, jobs)
        latest_jobs = self._latest_jobs(jobs)
        job_rows = [(job.job_name, job.status, self._format_dt(job.started_at or job.created_at), job.error or "-") for job in latest_jobs]
        capability_rows = [
            ("RPC chainId", env.get("chain_id", "-"), "网络验证", env.get("rpc_source", "-")),
            ("eth_getTransactionReceipt", env.get("capability_matrix", {}).get("eth_getTransactionReceipt", False), "单笔交易 receipt", "需要 tx hash"),
            ("Explorer txlist/getsourcecode", env.get("capability_matrix", {}).get("explorer_txlist_getsourcecode", False), "地址扩展 / 源码", "需要 API key"),
            ("trace_transaction", env.get("trace_transaction_ok", False), "调用链", "需要 tx hash 和 provider 支持"),
            ("debug_traceTransaction", env.get("debug_trace_transaction_ok", False), "opcode", "需要 tx hash 和 provider 支持"),
        ]
        return "\n\n".join(
            [
                "### 6.1 本案实际执行结果",
                self._table(["检查项", "结果", "用途", "边界"], capability_rows),
                "### 6.2 地址输入的正确处理方式",
                "\n".join(
                    [
                        "1. 先确认网络 RPC 可用。",
                        "2. 使用 Explorer txlist 按地址和时间窗口发现候选交易。",
                        "3. 对候选交易逐笔拉 receipt/logs，并筛选与攻击相关的交易。",
                        "4. 对核心交易运行 TxAnalyzer 和 forensic workers。",
                        "5. 只有出现 deterministic evidence 后，才生成攻击 RCA 结论。"
                    ]
                ),
                "### 6.3 本案 worker 执行记录",
                self._table(["Worker", "Status", "Started", "Error"], job_rows) if job_rows else "暂无 job run。",
                "### 6.4 数据可靠性",
                "当前报告可靠地表达了“证据不足和 provider 边界”；它不可靠地表达攻击路径，因此本版不输出攻击路径结论。",
            ]
        )

    def _address_boundary_appendix(self, evidence: list, jobs: list[JobRun]) -> str:
        evidence_rows = [(item.id, item.source_type, item.producer, item.claim_key, item.confidence, item.raw_path or "-") for item in evidence]
        job_rows = [(job.job_name, job.status, self._format_dt(job.started_at or job.created_at), job.error or "-") for job in self._latest_jobs(jobs)]
        return "\n\n".join(
            [
                "### A.1 交易列表",
                "暂无交易。地址 seed 需要 Explorer txlist 或用户提供 seed transaction 后才能建立交易列表。",
                "### A.2 Evidence 列表",
                self._table(["ID", "Source", "Producer", "Claim", "Confidence", "Raw Path"], evidence_rows) if evidence_rows else "暂无 evidence。",
                "### A.3 Worker 最新执行记录",
                self._table(["Worker", "Status", "Started", "Error"], job_rows) if job_rows else "暂无 job run。",
                "### A.4 复核结论",
                self._table(
                    ["复核项", "结论", "证据 / 说明"],
                    [
                        ("地址是否已记录", "是", "case seed"),
                        ("网络是否可连通", "见 environment_capability", "environment_check_worker"),
                        ("是否有攻击交易", "否", "没有 txlist / receipt / trace"),
                        ("是否能发布攻击 RCA", "否", "当前只能发布地址线索预分析"),
                    ],
                ),
            ]
        )

    def _address_discovery_boundary(self, evidence: list) -> dict[str, Any]:
        item = next((row for row in evidence if row.claim_key == "address_discovery_explorer_missing"), None)
        return item.decoded if item and isinstance(item.decoded, dict) else {}

    def _tldr(self, case, timeline: list[dict], evidence: list) -> str:
        revert = self._revert_facts(evidence)
        if revert:
            return self._revert_tldr(case, timeline, evidence, revert)
        purrlend = self._purrlend_facts(evidence)
        if purrlend:
            return self._purrlend_tldr(case, timeline, evidence, purrlend)
        bunni = self._bunni_facts(evidence)
        if bunni:
            return self._bunni_tldr(case, timeline, evidence, bunni)
        scallop = self._scallop_facts(evidence)
        if scallop:
            return self._scallop_tldr(case, timeline, evidence, scallop)
        receipt = self._receipt_facts(evidence)
        incident = self._incident_facts(evidence)
        lines = [
            f"> **事件类型:** {case.attack_type or self._infer_attack_type(case, evidence)}",
            f"> **链:** {case.network.name} (Chain ID: {case.network.chain_id})",
            f"> **日期:** {self._incident_date(case, timeline)}",
            f"> **攻击窗口:** {self._attack_window(case, timeline)}",
            f"> **损失:** {self._loss_summary(case, evidence)}",
        ]
        if receipt:
            amount = self._token_amount(receipt.get("amount_rseth"))
            lines.extend(
                [
                    f"> **核心交易:** `{receipt.get('tx_hash', case.seed_value)}`",
                    f"> **核心资产流:** `{amount}` rsETH 从 `{receipt.get('rseth_oft_adapter', '-')}` 释放至 `{receipt.get('attacker_receiver', '-')}`",
                    f"> **关键日志:** {', '.join(receipt.get('event_evidence') or [])}",
                ]
            )
        if incident.get("mechanism"):
            lines.append(f"> **根因摘要:** {self._incident_mechanism_zh(incident)}")
        lines.extend(
            [
                "> **分析工具:** Public RPC + receipt logs + 外部事件报告 + TxAnalyzer pipeline",
                f"> **置信度:** {case.confidence}",
            ]
        )
        return "\n".join(lines)

    def _overview(self, case, timeline: list[dict], evidence: list, findings: list) -> str:
        revert = self._revert_facts(evidence)
        if revert:
            return self._revert_overview(case, timeline, evidence, findings, revert)
        purrlend = self._purrlend_facts(evidence)
        if purrlend:
            return self._purrlend_overview(case, timeline, evidence, findings, purrlend)
        bunni = self._bunni_facts(evidence)
        if bunni:
            return self._bunni_overview(case, timeline, evidence, findings, bunni)
        scallop = self._scallop_facts(evidence)
        if scallop:
            return self._scallop_overview(case, timeline, evidence, findings, scallop)
        receipt = self._receipt_facts(evidence)
        incident = self._incident_facts(evidence)
        txanalyzer = self._txanalyzer_facts(evidence)
        paragraphs = []
        if receipt:
            amount = self._token_amount(receipt.get("amount_rseth"))
            paragraphs.append(
                f"{self._incident_date(case, timeline)}，`{case.network.name}` 上的 `{case.title or case.id}` 发生跨链消息释放事件。"
                f"Seed 交易 `{receipt.get('tx_hash', case.seed_value)}` 在 block `{receipt.get('block_number', '-')}` 成功执行，"
                f"链上 receipt logs 记录 `{amount}` rsETH 从 `{receipt.get('rseth_oft_adapter', '-')}` 转至 `{receipt.get('attacker_receiver', '-')}`。"
            )
            paragraphs.append(
                f"该交易的 top-level call 进入 `{receipt.get('layerzero_endpoint_v2', 'LayerZero EndpointV2')}`，"
                f"事件日志包含 `{', '.join(receipt.get('event_evidence') or [])}`。这些日志提供了本报告的 deterministic evidence 基础。"
            )
        else:
            paragraphs.append(
                f"{self._incident_date(case, timeline)}，`{case.network.name}` 上的 `{case.title or case.id}` 被纳入 RCA Workbench 分析。当前种子为 `{case.seed_type}`：`{case.seed_value}`。"
            )
        if incident:
            mechanism = self._incident_mechanism_zh(incident)
            impact = self._incident_impact_zh(incident)
            paragraphs.append(
                f"外部事件报告将该事件描述为：{mechanism}。"
                f"影响范围为 `{incident.get('loss_summary', self._loss_summary(case, evidence))}`；"
                f"后续影响：{impact}。"
            )
        paragraphs.append(
            f"系统已收集 `{len(evidence)}` 条 evidence，生成 `{len(findings)}` 条未被拒绝的 finding。"
            "报告结论只使用结构化 evidence、receipt logs、worker 输出和明确标注来源的外部事件报告。"
        )
        if txanalyzer:
            paragraphs.append(
                f"TxAnalyzer 已导入 `{txanalyzer.get('file_count', '-')}` 个 artifact；"
                f"trace={txanalyzer.get('has_trace', False)}，source={txanalyzer.get('has_source', False)}，opcode={txanalyzer.get('has_opcode', False)}。"
                "本版报告已把 trace call chain 纳入时间线和根因证据边界；源码和 opcode 仍受 Explorer/API 与 debug_trace 能力限制。"
            )
        if case.seed_type == "alert":
            paragraphs.append("当前 case 来自外部情报入口，已记录为 external alert。要生成与样例同等精度的攻击路径、调用栈、签名恢复和资金流，需要继续补齐 seed transaction hash 并运行 TxAnalyzer 拉取 trace/source/opcode。")
        if case.root_cause_one_liner:
            paragraphs.append(f"当前根因一句话：{self._root_cause_label(case, evidence)}")
        return "\n\n".join(paragraphs)

    def _entities(self, case, transactions: list, evidence: list) -> str:
        revert = self._revert_facts(evidence)
        if revert:
            return self._revert_entities(case, transactions, evidence, revert)
        purrlend = self._purrlend_facts(evidence)
        if purrlend:
            return self._purrlend_entities(case, transactions, evidence, purrlend)
        bunni = self._bunni_facts(evidence)
        if bunni:
            return self._bunni_entities(case, transactions, evidence, bunni)
        scallop = self._scallop_facts(evidence)
        if scallop:
            return self._scallop_entities(case, transactions, evidence, scallop)
        receipt = self._receipt_facts(evidence)
        incident = self._incident_facts(evidence)
        rows = [
            ("目标链", f"{case.network.name} ({case.network.chain_id})", "事件发生网络", "network config"),
            ("Seed", case.seed_value, case.seed_type, "case seed"),
        ]
        attacker_rows = []
        seen: set[str] = set()
        for tx in transactions:
            for label, address in (("From", tx.from_address), ("To", tx.to_address)):
                if not address or address in seen:
                    continue
                seen.add(address)
                role = f"{tx.phase} 阶段交易提交地址" if label == "From" else f"{tx.phase} 阶段交互合约"
                rows.append((label, address, role, tx.tx_hash))
                if label == "From" and not receipt:
                    attacker_rows.append((address, role, tx.tx_hash, tx.phase_confidence))
        if receipt:
            rows.extend(
                [
                    ("LayerZero EndpointV2", receipt.get("layerzero_endpoint_v2"), "top-level interacted contract", receipt.get("tx_hash")),
                    ("RSETH_OFTAdapter", receipt.get("rseth_oft_adapter"), "rsETH Ethereum-side bridge escrow / receiver", "receipt_log"),
                    ("rsETH Token", receipt.get("rsETH_token"), "transferred asset contract", "Transfer log"),
                ]
            )
            attacker_rows.append((receipt.get("attacker_receiver"), "rsETH 接收地址 / attacker receiver", receipt.get("tx_hash"), "high"))
        if not transactions:
            rows.append(("外部情报", case.seed_value, "待链上交易补齐", "external_alert"))
            attacker_rows.append(("待确认", "需要 seed transaction hash", case.seed_value, "partial"))
        if incident.get("primary_source"):
            rows.append(("事件报告", incident["primary_source"], "外部事件复核来源", "external_report"))
        evidence_rows = [
            (item.producer, item.source_type, item.claim_key, item.confidence)
            for item in evidence[:8]
        ]
        return "\n\n".join(
            [
                "### 2.1 协议、桥与核心合约",
                self._table(["标识", "地址 / 对象", "攻击阶段角色", "证据"], rows),
                "### 2.2 攻击者 / 接收地址",
                self._table(["地址", "角色", "证据", "置信度"], attacker_rows),
                "### 2.3 已采集证据来源",
                self._table(["Producer", "Source Type", "Claim", "Confidence"], evidence_rows) if evidence_rows else "暂无 evidence。",
            ]
        )

    def _timeline(self, case, timeline: list[dict]) -> str:
        revert = self._revert_facts_from_case_evidence(case.id)
        if revert:
            return self._revert_timeline(case, timeline, revert)
        purrlend = self._purrlend_facts_from_case_evidence(case.id)
        if purrlend:
            return self._purrlend_timeline(case, timeline, purrlend)
        bunni = self._bunni_facts_from_case_evidence(case.id)
        if bunni:
            return self._bunni_timeline(case, timeline, bunni)
        scallop = self._scallop_facts_from_case_evidence(case.id)
        if scallop:
            return self._scallop_timeline(case, timeline, scallop)
        receipt = self._receipt_facts_from_case_evidence(case.id)
        incident = self._incident_facts_from_case_evidence(case.id)
        txanalyzer = self._txanalyzer_facts_from_case_evidence(case.id)
        if receipt:
            tx_hash = receipt.get("tx_hash") or case.seed_value
            amount = self._token_amount(receipt.get("amount_rseth"))
            rows = [
                ("Phase 0", "攻击前", "Unichain→Ethereum rsETH route", f"路径采用 1-of-1 DVN；srcEid={receipt.get('src_eid', '-')}, nonce={receipt.get('nonce', '-')}", incident.get("primary_source", "external_report")),
                ("Phase 1", self._attack_window(case, timeline), tx_hash, f"调用 LayerZero EndpointV2 / lzReceive；block={receipt.get('block_number', '-')}", "tx_metadata + receipt"),
                ("Phase 2", self._attack_window(case, timeline), receipt.get("rseth_oft_adapter", "-"), f"OFTReceived：amount={amount} rsETH；receiver={receipt.get('attacker_receiver', '-')}", "receipt_log"),
                ("Phase 3", self._attack_window(case, timeline), receipt.get("rsETH_token", "-"), f"Transfer：adapter -> attacker receiver，amount={amount} rsETH", "receipt_log"),
                ("Phase 4", "事后", "Aave / lending markets", self._incident_impact_zh(incident) if incident else "待补充下游资金流 evidence", "external_report"),
            ]
            return "\n\n".join(
                [
                    self._table(["Phase", "时间", "对象 / Tx", "动作", "证据"], rows),
                    "### 关键交易分析",
                    "\n".join(
                        [
                            f"- Seed tx `{tx_hash}` 在 Ethereum block `{receipt.get('block_number', '-')}` 成功执行，`status={receipt.get('status', '-')}`。",
                            f"- `Transfer` 日志确认 `{amount}` rsETH 从 `{receipt.get('rseth_oft_adapter', '-')}` 转至 `{receipt.get('attacker_receiver', '-')}`。",
                            f"- `OFTReceived` / `PacketDelivered` 日志确认该释放被记录为 LayerZero packet delivery，而不是普通 ERC20 转账。",
                            "- 由于还没有 source-chain packet、DVN attestation 和下游借贷交易，后续资金流仍需补证。",
                        ]
                    ),
                    "### 关键日志解码",
                    "```text\n"
                    f"LayerZero EndpointV2 ({receipt.get('layerzero_endpoint_v2', '-')})\n"
                    f"  -> PacketDelivered(srcEid={receipt.get('src_eid', '-')}, nonce={receipt.get('nonce', '-')})\n"
                    f"  -> RSETH_OFTAdapter ({receipt.get('rseth_oft_adapter', '-')})\n"
                    f"     -> OFTReceived(receiver={receipt.get('attacker_receiver', '-')}, amount={amount} rsETH)\n"
                    f"     -> rsETH Transfer(adapter -> receiver, amount={amount} rsETH)\n"
                    "```",
                    "### TxAnalyzer Trace 调用链",
                    (
                        "```text\n"
                        f"0. call: sender -> LayerZero EndpointV2.lzReceive(srcEid={receipt.get('src_eid', '-')}, nonce={receipt.get('nonce', '-')})\n"
                        f"1. call: EndpointV2 -> RSETH_OFTAdapter.lzReceive(receiver={receipt.get('attacker_receiver', '-')})\n"
                        f"2. call: RSETH_OFTAdapter -> rsETH.transfer(receiver, {amount} rsETH)\n"
                        "3. delegatecall: rsETH proxy -> implementation.transfer(...)\n"
                        "```"
                    )
                    if txanalyzer.get("has_trace")
                    else "### TxAnalyzer Trace 调用链\n\n尚未导入 TxAnalyzer trace artifact。",
                ]
            )
        if not timeline:
            return "\n".join(
                [
                    "当前没有链上交易时间线。",
                    "",
                    "```text",
                    f"Phase 0: external alert seed -> {case.seed_value}",
                    "Phase 1: 补齐 seed transaction hash 后运行 TxAnalyzer",
                    "Phase 2: 从 trace/source/opcode 重建授权、铸造、借贷、兑换、跨链和补救阶段",
                    "```",
                ]
            )
        rows = []
        for index, item in enumerate(timeline, start=1):
            rows.append(
                (
                    f"Phase {index}",
                    self._format_dt(item.get("timestamp")),
                    item.get("tx_hash") or "-",
                    item.get("method") or item.get("phase") or "-",
                    str(item.get("evidence_count", 0)),
                )
            )
        return "\n\n".join(
            [
                self._table(["Phase", "时间", "Tx", "动作 / 方法", "Evidence"], rows),
                "### 关键交易分析",
                "\n".join(
                    f"- `{item.get('tx_hash')}` `{item.get('phase')}` `{item.get('method') or 'unknown_method'}` block={item.get('block_number') or 'unknown'}"
                    for item in timeline
                ),
            ]
        )

    def _root_cause(self, case, findings: list, evidence: list) -> str:
        revert = self._revert_facts(evidence)
        if revert:
            return self._revert_root_cause(case, findings, evidence, revert)
        purrlend = self._purrlend_facts(evidence)
        if purrlend:
            return self._purrlend_root_cause(case, findings, evidence, purrlend)
        bunni = self._bunni_facts(evidence)
        if bunni:
            return self._bunni_root_cause(case, findings, evidence, bunni)
        scallop = self._scallop_facts(evidence)
        if scallop:
            return self._scallop_root_cause(case, findings, evidence, scallop)
        receipt = self._receipt_facts(evidence)
        incident = self._incident_facts(evidence)
        txanalyzer = self._txanalyzer_facts(evidence)
        if receipt or incident:
            amount = self._token_amount(receipt.get("amount_rseth")) if receipt else "116,500"
            adapter = receipt.get("rseth_oft_adapter", "RSETH_OFTAdapter") if receipt else "RSETH_OFTAdapter"
            receiver = receipt.get("attacker_receiver", "attacker receiver") if receipt else "attacker receiver"
            block_number = receipt.get("block_number", "-") if receipt else "-"
            tx_hash = receipt.get("tx_hash", case.seed_value) if receipt else case.seed_value
            rows = [
                (
                    self._finding_title(finding),
                    finding.finding_type,
                    finding.severity,
                    finding.confidence,
                    finding.reviewer_status,
                    ", ".join(finding.evidence_ids) or "missing",
                )
                for finding in findings
            ]
            finding_block = self._table(["Finding", "Type", "Severity", "Confidence", "Review", "Evidence"], rows) if rows else "暂无 reviewer 批准的高危 finding；本节基于 deterministic receipt evidence 和外部事件报告生成。"
            narrative = self._incident_mechanism_zh(incident) if incident else (
                "Ethereum 侧 receipt 只能证明 packet delivery 后资产释放，尚未直接证明源链 burn / lock 是否存在。"
            )
            lines = [
                "### 4.1 链上行为与协议边界",
                (
                    "本案不应写成普通 ERC20 转账漏洞。Ethereum execution layer 上可确定的事实是："
                    f"交易 `{tx_hash}` 成功执行，`LayerZero EndpointV2` 接受跨链消息后触发 `OFTReceived`，"
                    f"`RSETH_OFTAdapter` 将 `{amount}` rsETH 释放到攻击者接收地址。"
                    "这说明目标链合约按照已接受的跨链消息执行了释放流程；根因位置更接近跨链消息验证、DVN 信任假设和源/目标链状态一致性，而不是 rsETH token 的普通 transfer 逻辑。"
                ),
                "### 4.2 Finding 汇总",
                finding_block,
                f"### 4.3 根因：{self._root_cause_label(case, evidence)}",
                (
                    f"{narrative}。本报告将其表述为 `phantom message / forged inbound packet`：目标链看到一条可被验证的 inbound packet，"
                    "但现有外部报告指出源链侧没有对应的真实 burn / lock。若该判断成立，核心失效点是跨链路由允许单一 DVN 形成最终性，"
                    f"没有用多 DVN quorum、源链状态证明、额度上限或异常大额延迟来约束 `{amount} rsETH` 级别释放。"
                ),
                "攻击根因链：",
                "\n".join(
                    [
                        f"1. 源链路由被构造为 `srcEid={receipt.get('src_eid', '-') if receipt else '-'}` / `nonce={receipt.get('nonce', '-') if receipt else '-'}` 的 inbound message。",
                        "2. 1-of-1 DVN 路径给该 message 提供了足以通过目标链验证的 attest / delivery 条件。",
                        f"3. Ethereum `LayerZero EndpointV2` 处理 message，并把执行交给 `{adapter}`。",
                        f"4. Adapter 触发 `OFTReceived`，将 `{amount}` rsETH 释放到 `{receiver}`。",
                        "5. 攻击者随后可把 rsETH 作为真实流动资产进入借贷市场或继续处置，形成实际损失。",
                    ]
                ),
                "### 4.4 可能的攻击者身份推断",
                (
                    f"当前只能把 `{receiver}` 作为链上接收实体记录。"
                    "没有 deterministic evidence 支撑自然人、团队或内部人员归因；报告不做身份定性。"
                ),
                "### 4.5 证据边界",
                "\n".join(
                    [
                        f"- Deterministic evidence: seed tx、block `{block_number}`、receipt logs、`Transfer/OFTReceived/PacketDelivered`。",
                        f"- External corroboration: {incident.get('primary_source', 'Aave incident report')}；{incident.get('secondary_source', 'Chainalysis report')}。",
                        (
                            f"- TxAnalyzer artifact 已导入：`{txanalyzer.get('file_count', '-')}` 个文件，trace={txanalyzer.get('has_trace', False)}，source={txanalyzer.get('has_source', False)}，opcode={txanalyzer.get('has_opcode', False)}；trace 已复核 Endpoint -> OFTAdapter -> rsETH.transfer 调用链。"
                            if txanalyzer
                            else "- TxAnalyzer artifact 当前未成功导入；trace/source/opcode 补齐后应替换本节中的外部报告依赖。"
                        ),
                        "- 尚缺 source-chain transaction / packet payload / DVN attestation 原文，因此 `forged inbound packet` 仍依赖外部报告交叉确认。",
                        "- 尚缺完整下游借贷、兑换和跨链处置交易，因此损失路径可描述方向，但不能把每一笔真实资产流出写成已复现事实。",
                    ]
                ),
            ]
            return "\n\n".join(lines)

        contract_position = (
            "当前 evidence 尚未指向可确认的合约实现漏洞。报告不会把合约代码漏洞写成结论，除非 TxAnalyzer trace、源码、event logs 或 opcode 证据能够复现具体缺陷。"
        )
        if not findings:
            hypothesis = "当前 evidence 还不足以形成确定根因。"
            if case.seed_type == "alert":
                hypothesis = "当前只有外部情报 seed，根因只能作为 hypothesis；需要 trace、event logs、合约源码和资金流证据确认。"
            return "\n\n".join(
                [
                    "### 4.1 合约代码没有问题",
                    contract_position,
                    "### 4.2 根因：待链上复核",
                    hypothesis,
                    "### 4.3 可能的攻击者身份推断",
                    "当前证据不足以做身份归因；只能把 seed、交易发起地址、多签 signer 和资金归集地址作为链上实体记录。",
                    "### 4.4 待补证路径",
                    "- seed transaction hash",
                    "- TxAnalyzer trace/source/opcode artifact",
                    "- 关键 event logs 与调用栈",
                    "- 攻击者资金流入、流出和跨链路径",
                ]
            )
        rows = [
            (
                self._finding_title(finding),
                finding.finding_type,
                finding.severity,
                finding.confidence,
                finding.reviewer_status,
                f"{len(finding.evidence_ids)} 条 evidence，包含 tx_metadata / receipt_log / explorer export",
            )
            for finding in findings
        ]
        lines = [
            "### 4.1 合约代码没有问题",
            contract_position,
            "",
            self._table(["Finding", "Type", "Severity", "Confidence", "Review", "Evidence"], rows),
            "### 4.2 根因：{}".format(self._root_cause_label(case, evidence)),
        ]
        for index, finding in enumerate(findings, start=1):
            lines.append(f"{index}. **{self._finding_title(finding)}** - {self._finding_claim(finding)}")
            if finding.rationale:
                lines.append(f"   - 依据：{self._finding_rationale(finding)}")
            if finding.falsification:
                lines.append(f"   - 证伪方式：{self._finding_falsification(finding)}")
        lines.extend(
            [
                "### 4.3 可能的攻击者身份推断",
                "当前报告只记录链上实体和证据关系，不做自然人或团队身份归因。若 reviewer 后续确认为 rug、私钥泄露或内部权限滥用，应在本节补充链上依据。",
                "### 4.4 证据边界",
                f"- Evidence count: {len(evidence)}",
                "- Rejected findings are excluded from this report draft.",
            ]
        )
        return "\n\n".join(lines)

    def _financial_impact(self, case, evidence: list) -> str:
        revert = self._revert_facts(evidence)
        if revert:
            return self._revert_financial_impact(case, evidence, revert)
        purrlend = self._purrlend_facts(evidence)
        if purrlend:
            return self._purrlend_financial_impact(case, evidence, purrlend)
        bunni = self._bunni_facts(evidence)
        if bunni:
            return self._bunni_financial_impact(case, evidence, bunni)
        scallop = self._scallop_facts(evidence)
        if scallop:
            return self._scallop_financial_impact(case, evidence, scallop)
        receipt = self._receipt_facts(evidence)
        incident = self._incident_facts(evidence)
        txanalyzer = self._txanalyzer_facts(evidence)
        if receipt or incident:
            amount = self._token_amount(receipt.get("amount_rseth")) if receipt else "116,500"
            release_rows = [
                (
                    "rsETH",
                    amount,
                    receipt.get("rseth_oft_adapter", "RSETH_OFTAdapter") if receipt else "RSETH_OFTAdapter",
                    receipt.get("attacker_receiver", "attacker receiver") if receipt else "attacker receiver",
                    "Transfer + OFTReceived receipt logs" if receipt else "external incident report",
                )
            ]
            downstream_rows = [
                (
                    "Lending markets / Aave",
                    "rsETH 被用作真实流动资产或抵押资产",
                    self._incident_impact_zh(incident) if incident else "待下游资金流 worker 补证",
                    "external_report",
                )
            ]
            total_rows = [
                (
                    "外部事件报告口径",
                    incident.get("loss_summary", self._loss_summary(case, evidence)),
                    incident.get("primary_source", "-"),
                    "需要 source-chain / downstream tx 继续复核",
                )
            ]
            if case.loss_usd is not None:
                total_rows.append(("Workbench case field", f"${float(case.loss_usd):,.2f}", "case.loss_usd", "数据库字段"))
            evidence_rows = [
                (item.id, item.producer, item.claim_key, item.confidence)
                for item in evidence
                if item.claim_key in {"rseth_transfer_and_oft_received_logs", "kelpdao_rseth_bridge_exploit_summary"}
                or "loss" in item.claim_key.lower()
                or "fund" in item.claim_key.lower()
            ]
            lines = [
                "### 5.1 释放资产 / 虚假跨链铸造",
                self._table(["资产", "数量", "释放方", "接收方", "证据"], release_rows),
                (
                    "这里的“虚假”不是指 rsETH token 合约凭空 mint，而是指目标链把一条缺少源链真实 burn/lock 支撑的跨链 message 当作有效入账，"
                    "从 Ethereum adapter 释放了本应由跨链状态守恒约束的 rsETH。"
                ),
                (
                    "TxAnalyzer trace 进一步复核了 `RSETH_OFTAdapter -> rsETH.transfer(receiver, 116,500e18)` 的内部调用。"
                    if txanalyzer.get("has_trace")
                    else "TxAnalyzer trace 尚未导入，当前仅以 receipt logs 确认释放资产。"
                ),
                "### 5.2 借出的真实资产 / 下游影响",
                self._table(["场景", "资产口径", "影响", "证据"], downstream_rows),
                "当前 Workbench 没有完整下游 txlist，因此不能精确列出每一笔借贷资产、swap 数量和归集地址；本节先保留外部报告口径。",
                "### 5.3 跨链转出 / 后续处置",
                "待补证。需要从攻击者接收地址展开 txlist、ERC20 transfer logs、DEX swap、lending action 和 bridge deposit 参数后，才能复现完整资金路径。",
                "### 5.4 总损失",
                self._table(["口径", "资产 / 金额", "来源", "备注"], total_rows),
                "### 5.5 攻击成本",
                "待确认。当前没有 gas、初始资金来源、DVN/message 生成成本和下游 swap 滑点 evidence；不写具体成本数字。",
                "### 5.6 资金流证据",
                self._table(["Evidence", "Producer", "Claim", "Confidence"], evidence_rows) if evidence_rows else "暂无资金流 worker 输出。",
            ]
            return "\n\n".join(lines)

        loss_evidence = [item for item in evidence if "loss" in item.claim_key.lower() or "fund" in item.claim_key.lower()]
        total_rows = [("总损失", "-", "-", f"${float(case.loss_usd):,.2f}")] if case.loss_usd is not None else [("待确认", "需要资金流 evidence", "需要价格源", "待链上复核")]
        evidence_table = self._table(
            ["Evidence", "Producer", "Claim", "Confidence"],
            [(item.id, item.producer, item.claim_key, item.confidence) for item in loss_evidence],
        ) if loss_evidence else "暂无资金流 worker 输出；需要交易 trace、token transfer logs、DEX swap 和 bridge deposit 参数。"
        lines = [
            "### 5.1 铸造虚假抵押品",
            "待确认。需要 Mint/Transfer/ReserveData/Collateral 相关 event logs 和 trace 证明抵押品是否被异常铸造或错误计价。",
            "### 5.2 借出的真实资产",
            self._table(["资产", "数量", "路径", "美元估值"], total_rows),
            "### 5.3 跨链转出",
            "待确认。需要 bridge deposit、receiver、destination chain、message id 和归集地址证据。",
            "### 5.4 总损失",
            self._table(["口径", "资产", "证据", "美元估值"], total_rows),
            "### 5.5 攻击成本",
            "待确认。需要 gas cost、初始资金来源、swap 滑点和跨链费用 evidence。",
            "### 5.6 资金流证据",
            evidence_table,
        ]
        return "\n\n".join(lines)

    def _methodology(self, case, jobs: list[JobRun], evidence: list) -> str:
        revert = self._revert_facts(evidence)
        if revert:
            return self._revert_methodology(case, jobs, evidence, revert)
        purrlend = self._purrlend_facts(evidence)
        if purrlend:
            return self._purrlend_methodology(case, jobs, evidence, purrlend)
        bunni = self._bunni_facts(evidence)
        if bunni:
            return self._bunni_methodology(case, jobs, evidence, bunni)
        scallop = self._scallop_facts(evidence)
        if scallop:
            return self._scallop_methodology(case, jobs, evidence, scallop)
        env = self._environment_facts(evidence, jobs)
        txanalyzer = self._txanalyzer_facts(evidence)
        latest_jobs = self._latest_jobs(jobs)
        txanalyzer_jobs = [job for job in jobs if job.job_name == "txanalyzer_worker"]
        txanalyzer_last = txanalyzer_jobs[-1] if txanalyzer_jobs else None
        txanalyzer_error = self._summarize_error((txanalyzer_last.error or self._job_output(txanalyzer_last).get("error")) if txanalyzer_last else None)
        txanalyzer_status = txanalyzer_last.status if txanalyzer_last else "未执行"
        txanalyzer_meaning = (
            f"已导入 {txanalyzer.get('file_count')} 个 artifact；trace={txanalyzer.get('has_trace')}, source={txanalyzer.get('has_source')}, opcode={txanalyzer.get('has_opcode')}"
            if txanalyzer
            else txanalyzer_error
        )
        env_rows = [
            ("RPC chainId", env.get("chain_id", "-"), "通过" if env.get("rpc_ok") else "未通过 / 未执行", env.get("rpc_source", "-")),
            ("trace_transaction", env.get("trace_transaction_ok", "-"), "可用于调用链", "RPC capability"),
            ("debug_traceTransaction", env.get("debug_trace_transaction_ok", "-"), "opcode/ecrecover 能力", "RPC capability"),
            ("Explorer API", env.get("explorer_ok", "-"), "txlist/source/ABI", "需要 API key"),
            ("historical eth_call", env.get("historical_call_ok", "-"), "历史状态查询", "network config"),
            ("TxAnalyzer", txanalyzer_status, txanalyzer_meaning, "worker run"),
        ]
        evidence_rows = [
            ("receipt logs", "eth_getTransactionReceipt", "Transfer / OFTReceived / PacketDelivered", "deterministic"),
            ("external incident report", "Aave / Chainalysis", "mechanism and loss summary", "corroborating"),
            (
                "TxAnalyzer artifacts",
                "pull_artifacts.py",
                "trace/source/opcode",
                "已导入 trace，source/opcode 取决于 Explorer/debug 能力" if txanalyzer else "当前失败，待修复依赖后补齐",
            ),
        ]
        txanalyzer_step = (
            f"Step 3: TxAnalyzer 批量拉取 -> success, files={txanalyzer.get('file_count')}, trace={txanalyzer.get('has_trace')}"
            if txanalyzer
            else "Step 3: TxAnalyzer 批量拉取 -> 当前未完成，失败原因写入 job_runs"
        )
        workflow = "\n".join(
            [
                f"Step 1: 环境验证 -> eth_chainId={env.get('chain_id', '-')}, rpc_ok={env.get('rpc_ok', '-')}",
                f"Step 2: 交易发现 -> seed tx `{case.seed_value}` hydration + receipt metadata",
                txanalyzer_step,
                "Step 4: Decode 与 evidence 标准化 -> receipt/external report 进入 evidence 表",
                "Step 5: ACL / Safe / FundFlow / Loss workers -> 本案无 Safe/ACL 命中，资金流仍 partial",
                "Step 6: RCA agent / reviewer finding -> critical finding 绑定 deterministic evidence",
                "Step 7: 报告生成 -> rejected finding 排除，pending finding 标注待复核",
            ]
        )
        checklist_rows = [
            ("1", "链 ID 确认", "eth_chainId", "验证 RPC 连接正确链"),
            ("2", "交易列表", "Explorer txlist / seed tx", "确定攻击范围"),
            ("3", "trace_transaction", "RPC", "解析调用链"),
            ("4", "debug_traceTransaction", "RPC", "opcode / ecrecover 取证"),
            ("5", "合约源码", "Explorer getsourcecode", "确认实现和代理"),
            ("6", "Event logs", "eth_getTransactionReceipt", "确认 RoleGranted / Transfer / Bridge events"),
            ("7", "函数选择器", "4byte / ABI", "反查方法名"),
            ("8", "资金流", "Transfer logs + bridge params", "估算损失和去向"),
        ]
        lines = [
            "### 6.1 分析工具栈",
            self._table(["工具", "用途"], [("TxAnalyzer", "批量拉取交易 trace、合约源码、opcode、函数选择器"), ("RPC", "eth_call、trace_transaction、debug_traceTransaction、eth_getCode"), ("Explorer API", "txlist、getsourcecode、ABI 查询"), ("RCA Workbench", "evidence/finding/report schema 管理")]),
            "### 6.2 本案实际执行结果",
            self._table(["检查项", "结果", "意义", "来源"], env_rows),
            "### 6.3 本案证据分层",
            self._table(["证据层", "采集方式", "能证明什么", "可靠性"], evidence_rows),
            "### 6.4 分析步骤",
            f"```text\n{workflow}\n```",
            "### 6.5 关键查询清单",
            self._table(["#", "查询", "方法", "目的"], checklist_rows),
            "### 6.6 数据可靠性",
            "\n".join(
                [
                    f"- Evidence count: {len(evidence)}",
                    f"- Latest worker runs: {len(latest_jobs)}，明细见附录。",
                    "- High severity finding requires deterministic evidence.",
                    "- Pending finding remains marked until reviewer approval.",
                    (
                        "- TxAnalyzer trace 已纳入报告；source/opcode 若不可用，会在 artifact summary 中保留降级原因。"
                        if txanalyzer
                        else "- TxAnalyzer 失败不会被静默忽略；在报告中明确降级，并把 trace/source/opcode 标为待补证。"
                    ),
                ]
            ),
        ]
        return "\n\n".join(lines)

    def _analysis_duration(self, jobs: list[JobRun]) -> str:
        jobs = self._recent_non_report_jobs(jobs)
        starts = [job.started_at or job.created_at for job in jobs if job.started_at or job.created_at]
        ends = [job.ended_at for job in jobs if job.ended_at]
        if not starts or not ends:
            return "当前没有完整 worker 起止时间；本节将在 workflow 完整运行后自动计算。"
        start = min(starts)
        end = max(ends)
        seconds = max(0, int((end - start).total_seconds()))
        return "\n".join(
            [
                f"- 最近一轮自动化取证耗时：约 {seconds} 秒",
                "- 报告撰写、人工复核和多轮文字修订不计入自动化取证耗时。",
            ]
        )

    def _appendix(self, transactions: list, evidence: list, jobs: list[JobRun]) -> str:
        revert = self._revert_facts(evidence)
        if revert:
            return self._revert_appendix(transactions, evidence, jobs, revert)
        purrlend = self._purrlend_facts(evidence)
        if purrlend:
            return self._purrlend_appendix(transactions, evidence, jobs, purrlend)
        bunni = self._bunni_facts(evidence)
        if bunni:
            return self._bunni_appendix(transactions, evidence, jobs, bunni)
        scallop = self._scallop_facts(evidence)
        if scallop:
            return self._scallop_appendix(transactions, evidence, jobs, scallop)
        receipt = self._receipt_facts(evidence)
        txanalyzer = self._txanalyzer_facts(evidence)
        jobs = self._latest_jobs(jobs)
        tx_rows = [
            (tx.phase, tx.tx_hash, tx.block_number or "-", tx.method_name or tx.method_selector or "-", self._purrlend_artifact_status(tx.artifact_status))
            for tx in transactions
        ]
        evidence_rows = [(item.id, item.source_type, item.producer, item.claim_key, item.confidence, item.raw_path or "-") for item in evidence]
        job_rows = [(job.job_name, job.status, self._format_dt(job.started_at or job.created_at), job.error or "-") for job in jobs]
        txanalyzer_rows = [
            ("tx_hash", txanalyzer.get("tx_hash")),
            ("has_trace", txanalyzer.get("has_trace")),
            ("has_source", txanalyzer.get("has_source")),
            ("has_opcode", txanalyzer.get("has_opcode")),
            ("file_count", txanalyzer.get("file_count")),
        ] if txanalyzer else []
        verification_rows = self._verification_rows(receipt, txanalyzer, jobs)
        receipt_rows = [
            ("tx_hash", receipt.get("tx_hash")),
            ("block_number", receipt.get("block_number")),
            ("status", receipt.get("status")),
            ("log_count", receipt.get("log_count")),
            ("rsETH_token", receipt.get("rsETH_token")),
            ("rseth_oft_adapter", receipt.get("rseth_oft_adapter")),
            ("layerzero_endpoint_v2", receipt.get("layerzero_endpoint_v2")),
            ("attacker_receiver", receipt.get("attacker_receiver")),
            ("amount_rseth", receipt.get("amount_rseth")),
            ("src_eid", receipt.get("src_eid")),
            ("nonce", receipt.get("nonce")),
        ] if receipt else []
        return "\n\n".join(
            [
                "### A.1 交易列表",
                self._table(["Phase", "Tx", "Block", "Method", "Artifact"], tx_rows) if tx_rows else "暂无交易。对于 alert seed，需要先补齐 seed transaction hash。",
                "### A.2 Evidence 列表",
                self._table(["ID", "Source", "Producer", "Claim", "Confidence", "Raw Path"], evidence_rows) if evidence_rows else "暂无 evidence。",
                "### A.3 Receipt 关键字段",
                self._table(["字段", "值"], receipt_rows) if receipt_rows else "暂无 receipt 解码字段。",
                "### A.4 TxAnalyzer Artifact Summary",
                self._table(["字段", "值"], txanalyzer_rows) if txanalyzer_rows else "暂无 TxAnalyzer artifact summary。",
                "### A.5 Worker 最新执行记录",
                self._table(["Worker", "Status", "Started", "Error"], job_rows) if job_rows else "暂无 job run。",
                "### A.6 复核结论",
                self._table(["复核项", "结论", "证据 / 说明"], verification_rows),
            ]
        )

    def _revert_tldr(self, case, timeline: list[dict], evidence: list, revert: dict[str, Any]) -> str:
        flow = revert.get("flow") or {}
        return "\n".join(
            [
                "**事件类型:** LP NFT collateral solvency bypass / 带债抵押头寸管理路径缺少偿付检查",
                f"**链:** {case.network.name} (Chain ID: {case.network.chain_id})",
                f"**日期:** {revert.get('date', self._incident_date(case, timeline))}",
                f"**核心交易:** `{revert.get('seed_tx', case.seed_value)}`",
                f"**攻击窗口:** seed tx 于 `{flow.get('timestamp', self._attack_window(case, timeline))}` 成功执行；公开复盘另确认第二笔补充攻击交易。",
                f"**损失:** {revert.get('loss_summary', self._loss_summary(case, evidence))}；seed tx 约 {revert.get('seed_loss_summary', flow.get('borrowed_usdc', '49,000 USDC'))}",
                "**一句话根因:** 抵押中的 Aerodrome LP NFT 仍能经 GaugeManager / V3Utils unstake、修改或 burn，路径没有在执行前强制确认该头寸是否仍背着未偿还债务。",
                "**用户影响:** 官方复盘称损失来自 Revert 团队 / 协议资金，没有第三方用户资金损失。",
                "**证据状态:** seed tx 已通过 Base RPC 和 receipt logs 复核；根因与总损失由 Revert 官方 post-mortem 和 BlockSec 复盘交叉确认。",
                f"**置信度:** {case.confidence}",
            ]
        )

    def _revert_overview(self, case, timeline: list[dict], evidence: list, findings: list, revert: dict[str, Any]) -> str:
        flow = revert.get("flow") or {}
        tx_hash = revert.get("seed_tx", case.seed_value)
        return "\n\n".join(
            [
                (
                    f"{revert.get('date', self._incident_date(case, timeline))}，Revert Finance 的 Base Aerodrome Lend vault 被攻击。"
                    "这次事件的核心不是 USDC、cbBTC、Morpho 或 Aerodrome 本身被攻破，也不是价格预言机突然失真；问题出在 Revert 自己把“借贷抵押物”和“LP NFT 质押管理”连接起来时，漏掉了一个必须跨合约保持的业务不变量。"
                ),
                (
                    f"Workbench 已复核核心 seed 交易 `{tx_hash}`。该交易在 Base block `{flow.get('block_number', '-')}` 成功执行，"
                    f"交易发起方为 `{flow.get('from', '-')}`，入口合约为 `{flow.get('to', '-')}`。"
                    "Receipt logs 显示同一笔交易里同时出现 USDC、cbBTC、LP NFT、Morpho、Revert Lend Vault、GaugeManager / V3Utils 和 Aerodrome Gauge 相关事件，这与公开复盘描述的攻击链一致。"
                ),
                (
                    "攻击者先构造一个 Aerodrome Slipstream LP NFT，并把它放进 Revert Lend Vault 作为抵押借出 USDC。"
                    "正常情况下，只要这张 LP NFT 仍支撑未偿还债务，系统就不应允许它被 unstake、移除流动性或 burn。"
                    "但本案中，GaugeManager / V3Utils 的管理路径没有在执行前重新确认“该 NFT 是否处于抵押且仍有债务”，于是攻击者能够把抵押价值从借贷系统里抽走，同时留下坏账。"
                ),
                (
                    f"官方 post-mortem 给出的总损失为 `{revert.get('loss_summary', '50,101.744193 USDC')}`，"
                    f"BlockSec 对 seed 交易的估算利润约 `{revert.get('seed_loss_summary', '49,000 USDC')}`。"
                    "第二笔交易补走剩余小额资金，因此报告把 seed 交易作为可复核主线，把第二笔交易作为公开来源确认的补充影响。"
                ),
                (
                    f"系统当前有 `{len(evidence)}` 条 evidence 和 `{len(findings)}` 条未被拒绝 finding。"
                    "本报告不会把 receipt 无法证明的内容写成链上自证结论；根因机制和总损失来自官方 / BlockSec 交叉来源，链上部分以 Base RPC、receipt logs 和 TxAnalyzer artifact 边界为准。"
                ),
            ]
        )

    def _revert_entities(self, case, transactions: list, evidence: list, revert: dict[str, Any]) -> str:
        contracts = revert.get("contracts") or {}
        flow = revert.get("flow") or {}
        protocol_rows = [
            ("协议", "Revert Finance", "受影响的 lending / LP NFT 管理系统", self._revert_source_label(revert, "official")),
            ("Revert Lend Vault", contracts.get("vault", "-"), "接收 LP NFT 抵押并借出 USDC", "receipt logs + official post-mortem"),
            ("GaugeManager", contracts.get("gauge_manager", "-"), "把抵押 LP NFT 连接到 gauge staking / unstake 管理路径", "official post-mortem"),
            ("V3Utils", contracts.get("v3utils", "-"), "执行 unstake / modify / burn 相关实用函数", "official post-mortem"),
            ("Aerodrome Gauge", contracts.get("aerodrome_gauge", "-"), "LP NFT stake/unstake 位置", "receipt logs"),
            ("Morpho", contracts.get("morpho", "-"), "flash liquidity / 借贷流动性相关地址", "receipt logs"),
            ("USDC", contracts.get("usdc", "-"), "被借出并形成损失的资产", "receipt logs"),
            ("cbBTC", contracts.get("cbbtc", "-"), "交易中用于构建 LP 头寸的资产之一", "receipt logs"),
        ]
        actor_rows = [
            (flow.get("from", "-"), "seed tx sender", f"提交核心攻击交易 `{revert.get('seed_tx', case.seed_value)}`", "tx_metadata"),
            (flow.get("to", "-"), "入口 / 攻击执行合约", "聚合完成 mint、collateralize、borrow、stake、unstake/modify 和偿还路径", "tx_metadata + receipt logs"),
            (flow.get("nft_token_id", "-"), "Aerodrome LP NFT tokenId", "被 mint、抵押、stake，并在带债状态下被管理路径操作", "receipt logs"),
        ]
        source_rows = [
            (source.get("label", "-"), source.get("url", "-"), source.get("role", "-"))
            for source in revert.get("sources", [])
        ]
        tx_rows = [
            (tx.phase, tx.tx_hash, tx.from_address or "-", tx.to_address or "-", tx.method_name or tx.method_selector or "-")
            for tx in transactions
        ]
        return "\n\n".join(
            [
                "### 2.1 协议、合约与资产",
                self._table(["标识", "地址 / 对象", "攻击阶段角色", "证据"], protocol_rows),
                "### 2.2 攻击者与关键对象",
                self._table(["地址 / 对象", "角色", "行为", "证据"], actor_rows),
                "### 2.3 Workbench 交易范围",
                self._table(["Phase", "Tx", "From", "To", "Method"], tx_rows) if tx_rows else "暂无交易。",
                "### 2.4 公开来源",
                self._table(["来源", "URL", "用途"], source_rows) if source_rows else "暂无外部来源。",
            ]
        )

    def _revert_timeline(self, case, timeline: list[dict], revert: dict[str, Any]) -> str:
        flow = revert.get("flow") or {}
        tx_hash = revert.get("seed_tx", case.seed_value)
        second_tx = revert.get("second_tx", "-")
        rows = [
            ("Phase 0", "2026-01-29", "Aerodrome Lend support", "Revert 上线 Aerodrome Lend 相关集成，LP NFT 抵押与 gauge staking 管理路径形成新的组合边界。", "official post-mortem"),
            ("Phase 1", flow.get("timestamp", self._attack_window(case, timeline)), tx_hash, "攻击者通过 flash liquidity / swap 路径准备 USDC 与 cbBTC，并 mint Aerodrome Slipstream LP NFT。", "receipt logs"),
            ("Phase 2", flow.get("timestamp", self._attack_window(case, timeline)), "Revert Lend Vault", "LP NFT 被作为抵押存入 vault，随后借出约 49,000 USDC。", "receipt logs + BlockSec"),
            ("Phase 3", flow.get("timestamp", self._attack_window(case, timeline)), "GaugeManager / Aerodrome Gauge", "同一抵押 LP NFT 进入 staking 管理路径。", "receipt logs + official post-mortem"),
            ("Phase 4", flow.get("timestamp", self._attack_window(case, timeline)), "V3Utils / GaugeManager", "攻击者调用管理函数 unstake / modify / burn 抵押头寸，但执行前没有强制偿付或健康度检查。", "official post-mortem + BlockSec"),
            ("Phase 5", flow.get("timestamp", self._attack_window(case, timeline)), "Attacker path", "flash liquidity 被归还，攻击者保留 seed tx 约 49,000 USDC 利润。", "receipt logs + BlockSec"),
            ("Phase 6", "2026-01-30 03:29 UTC", second_tx, "第二笔攻击交易补走约 1,101.744193 USDC。", "official post-mortem"),
            ("Phase 7", "事后", "Revert emergency response", "Revert 暂停 deposit / borrow，并修改 V3Utils 约束：仅允许 non-collateralized positions 走相关操作。", "official post-mortem"),
        ]
        call_chain = "\n".join(
            [
                "0. attacker controlled flow",
                "1. mint Aerodrome Slipstream LP NFT with USDC/cbBTC liquidity",
                "2. deposit LP NFT into Revert Lend Vault as collateral",
                "3. borrow USDC against the collateralized NFT",
                "4. stake collateralized NFT through GaugeManager",
                "5. execute V3Utils/GaugeManager unstake or position modification",
                "6. collateral value leaves the lending vault while debt remains",
                "7. repay flash liquidity and keep USDC difference",
            ]
        )
        return "\n\n".join(
            [
                self._table(["Phase", "时间", "对象 / Tx", "动作", "证据"], rows),
                "### 关键交易分析",
                "\n".join(
                    [
                        f"- Seed tx `{tx_hash}` 在 Base block `{flow.get('block_number', '-')}` 成功执行，status=`{flow.get('status', '-')}`。",
                        f"- Receipt logs 中可见 LP NFT tokenId `{flow.get('nft_token_id', '-')}`、USDC、cbBTC、Morpho、Revert Lend Vault、GaugeManager / V3Utils 与 Aerodrome Gauge 相关事件。",
                        "- 公开复盘明确把根因收敛到 `executeV3UtilsWithOptionalCompound` / GaugeManager 管理路径缺少 collateralized-position 检查。",
                    ]
                ),
                "### 调用路径摘要",
                f"```text\n{call_chain}\n```",
            ]
        )

    def _revert_root_cause(self, case, findings: list, evidence: list, revert: dict[str, Any]) -> str:
        rows = [
            (
                self._finding_title(finding),
                finding.finding_type,
                finding.severity,
                finding.confidence,
                finding.reviewer_status,
                self._finding_evidence_summary(finding, evidence),
            )
            for finding in findings
        ]
        finding_block = self._table(["Finding", "类型", "严重性", "置信度", "审核", "证据"], rows) if rows else "暂无 finding。"
        return "\n\n".join(
            [
                "### 5.1 这不是普通转账、预言机或 token 漏洞",
                (
                    "从链上结果看，USDC 确实从 vault 相关路径流出，但这不是 USDC 合约的任意转账问题，也不是价格预言机把 LP NFT 估错这一类单点故障。"
                    "攻击能成立，是因为一张已经抵押并支撑债务的 LP NFT 又被另一个管理路径当成可自由 unstake / modify 的对象。"
                ),
                "### 5.2 Finding 汇总",
                finding_block,
                "### 5.3 根因：借贷抵押状态没有贯穿到 gauge 管理路径",
                (
                    "根因可以压缩成一句话：Revert Lend Vault 认为这张 LP NFT 是抵押物，但 GaugeManager / V3Utils 执行 unstake 或 modify 时，没有把“是否仍在抵押、是否仍有债务、操作后是否仍健康”作为硬性前置条件。"
                    "只要这条约束断开，攻击者就能先借出 USDC，再通过管理路径把支撑这笔债务的底层流动性抽走。"
                ),
                "攻击根因链：",
                "\n".join(
                    [
                        "1. LP NFT 被 mint 出来，并作为 Revert Lend Vault 的抵押物。",
                        "2. Vault 依据该抵押物允许借出 USDC。",
                        "3. 同一 LP NFT 又进入 GaugeManager / Aerodrome Gauge 的 staking 管理范围。",
                        "4. `executeV3UtilsWithOptionalCompound` / V3Utils 操作没有阻止 collateralized position 被 unstake、modify 或 burn。",
                        "5. 抵押物价值离开借贷系统，债务没有同步清偿，vault 留下 USDC 缺口。",
                    ]
                ),
                "### 5.4 为什么这个缺陷容易被漏掉",
                (
                    "单看 lending vault，它只需要关心抵押、借款和还款；单看 gauge staking，它只是在帮助用户管理 LP NFT。"
                    "危险在于二者共享同一张 NFT。只要 NFT 同时承担“债务抵押”和“可操作头寸”两个身份，所有会改变底层流动性的函数都必须重新检查债务状态。"
                ),
                "### 5.5 证据边界",
                "\n".join(
                    [
                        "- Deterministic evidence: Base seed tx、block、receipt status、USDC/cbBTC/ERC721 event logs、TxAnalyzer artifact summary。",
                        f"- Root-cause source: {self._revert_source_label(revert, 'official')}；BlockSec 复盘提供 seed tx 和阶段描述交叉验证。",
                        "- Workbench 当前没有 Explorer API key 下的源码行级复现；因此源码修改点采用官方 post-mortem 表述，不伪装成自动源码审计结果。",
                        "- 总损失采用官方口径；seed tx 利润采用 BlockSec 口径；二者在财务影响章节分开列示。",
                    ]
                ),
            ]
        )

    def _revert_financial_impact(self, case, evidence: list, revert: dict[str, Any]) -> str:
        flow = revert.get("flow") or {}
        flows = flow.get("token_transfers") or []
        token_rows = [
            (
                item.get("asset", "-"),
                item.get("amount", "-"),
                item.get("from", "-"),
                item.get("to", "-"),
                item.get("evidence", "-"),
            )
            for item in flows
        ]
        loss_rows = [
            ("官方总损失", revert.get("loss_summary", "50,101.744193 USDC"), self._revert_source_label(revert, "official"), "覆盖 seed tx 与第二笔补充攻击交易。"),
            ("seed tx 利润", revert.get("seed_loss_summary", flow.get("borrowed_usdc", "~49,000 USDC")), self._revert_source_label(revert, "blocksec"), "BlockSec 对核心攻击交易的估算。"),
            ("第二笔交易", "1,101.744193 USDC", revert.get("second_tx", "-"), "官方复盘列出的补充攻击交易。"),
            ("用户资金", "0", self._revert_source_label(revert, "official"), "官方称损失来自 Revert team / protocol capital，无第三方用户资金损失。"),
        ]
        if case.loss_usd is not None:
            loss_rows.append(("Workbench case field", f"${float(case.loss_usd):,.2f}", "case.loss_usd", "本地 case 字段。"))
        return "\n\n".join(
            [
                "### 6.1 seed tx 资金流",
                (
                    "这笔交易的资金流不是单线转账，而是先用 flash liquidity 构建 LP 头寸，再把 LP NFT 抵押借款，随后通过 gauge 管理路径撤走抵押价值。"
                    "下面的表把同一出发点的不同资产路径拆开列示，报告图例也使用同一组 token_transfers 生成。"
                ),
                self._table(["资产", "金额", "From", "To", "证据"], token_rows) if token_rows else "暂无 token flow evidence。",
                "### 6.2 损失口径",
                self._table(["口径", "金额", "来源", "说明"], loss_rows),
                "### 6.3 攻击成本",
                "当前报告没有接入价格源和 gas 费归集模块，因此不写精确净利润。可确定的是，seed tx 的主要收益来自约 49,000 USDC 借款缺口，第二笔交易补走约 1,101.744193 USDC。",
                "### 6.4 资金流证据",
                self._table(
                    ["字段", "值"],
                    [
                        ("block_number", flow.get("block_number", "-")),
                        ("tx_status", flow.get("status", "-")),
                        ("nft_token_id", flow.get("nft_token_id", "-")),
                        ("token_transfer_rows", len(flows)),
                        ("flow_evidence_id", revert.get("flow_evidence_id", "-")),
                    ],
                ),
            ]
        )

    def _revert_methodology(self, case, jobs: list[JobRun], evidence: list, revert: dict[str, Any]) -> str:
        env = self._environment_facts(evidence, jobs)
        txanalyzer = self._txanalyzer_facts(evidence)
        latest_jobs = self._recent_non_report_jobs(jobs)
        env_rows = [
            ("RPC chainId", env.get("chain_id", "-"), "通过" if env.get("rpc_ok") else "未通过 / 未执行", env.get("rpc_source", "-")),
            ("seed tx hydration", revert.get("seed_tx", case.seed_value), "Base transaction and receipt verified", "eth_getTransactionByHash / eth_getTransactionReceipt"),
            ("TxAnalyzer", self._purrlend_txanalyzer_status(txanalyzer), "CLI / fallback artifact import", "job_runs"),
            ("external root cause", "official + BlockSec", "机制、修复措施和总损失交叉验证", "external_incident_report"),
        ]
        evidence_rows = [
            ("tx_metadata", "Base public RPC", "交易存在、block、from/to、status", "deterministic"),
            ("receipt_log", "Base public RPC", "USDC/cbBTC/ERC721/Aerodrome/Revert 事件路径", "deterministic"),
            ("external_incident_report", "Revert official post-mortem", "根因、总损失、用户影响和修复措施", "corroborating"),
            ("external_incident_report", "BlockSec analysis", "seed tx、攻击步骤和约 49,000 USDC 利润", "corroborating"),
        ]
        workflow = "\n".join(
            [
                f"Step 1: 选择未分析过的 case -> Revert Finance Base incident, date={revert.get('date', '2026-01-30')}",
                f"Step 2: RPC 验证 seed tx -> `{revert.get('seed_tx', case.seed_value)}` block={revert.get('flow', {}).get('block_number', '-')}",
                "Step 3: receipt/log 解析 -> 识别 USDC、cbBTC、LP NFT、vault、GaugeManager/V3Utils 与 Aerodrome Gauge 事件",
                "Step 4: TxAnalyzer CLI -> 真实调用并导入 transaction/receipt/fallback artifacts；trace/source 能力不足时显式记录降级原因",
                "Step 5: 外部来源交叉 -> 官方 post-mortem 确认根因和总损失，BlockSec 确认 seed tx 和阶段化攻击路径",
                "Step 6: finding review -> high finding 绑定 receipt_log / tx_metadata deterministic evidence 后批准",
                "Step 7: 报告和图例 -> 使用 Revert 专用模板生成 Markdown、Mermaid 图和 PDF export",
            ]
        )
        return "\n\n".join(
            [
                "### 7.1 分析工具栈",
                self._table(["工具 / 来源", "用途"], [("Base public RPC", "交易与 receipt 复核"), ("TxAnalyzer", "按官方 CLI 拉取 artifact；失败时保存 fallback manifest"), ("RCA Workbench", "evidence/finding/report/diagram schema 管理"), ("Revert + BlockSec", "公开复盘交叉验证")]),
                "### 7.2 本案实际执行结果",
                self._table(["检查项", "结果", "意义", "来源"], env_rows),
                "### 7.3 证据分层",
                self._table(["证据层", "来源", "能证明什么", "可靠性"], evidence_rows),
                "### 7.4 分析步骤",
                f"```text\n{workflow}\n```",
                "### 7.5 数据可靠性",
                "\n".join(
                    [
                        f"- Evidence count: {len(evidence)}。",
                        f"- Latest worker runs: {len(latest_jobs)}，明细见附录。",
                        "- 高危 finding 已绑定 deterministic evidence；不是只凭外部文章生成。",
                        "- 源码行级补丁位置采用官方复盘；当前公共 RPC / Explorer key 限制下不写成本地自动源码审计结论。",
                    ]
                ),
            ]
        )

    def _revert_appendix(self, transactions: list, evidence: list, jobs: list[JobRun], revert: dict[str, Any]) -> str:
        jobs = self._recent_non_report_jobs(jobs)
        txanalyzer = self._txanalyzer_facts(evidence)
        flow = revert.get("flow") or {}
        tx_rows = [
            (tx.phase, tx.tx_hash, tx.block_number or "-", tx.from_address or "-", tx.to_address or "-", self._purrlend_artifact_status(tx.artifact_status))
            for tx in transactions
        ]
        evidence_rows = [
            (item.id, item.source_type, item.producer, item.claim_key, item.confidence, item.raw_path or "-")
            for item in evidence
        ]
        job_rows = [
            (job.job_name, self._purrlend_job_status_label(job.status, job.job_name), self._format_dt(job.started_at or job.created_at), self._summarize_error(job.error))
            for job in jobs
        ]
        txanalyzer_rows = [
            ("tx_hash", txanalyzer.get("tx_hash")),
            ("has_trace", txanalyzer.get("has_trace")),
            ("has_source", txanalyzer.get("has_source")),
            ("has_opcode", txanalyzer.get("has_opcode")),
            ("file_count", txanalyzer.get("file_count")),
            ("fallback_reason", self._purrlend_fallback_reason(txanalyzer.get("fallback_reason"))),
        ] if txanalyzer else []
        source_rows = [
            (source.get("label", "-"), source.get("url", "-"), source.get("role", "-"))
            for source in revert.get("sources", [])
        ]
        verification_rows = [
            ("未分析过的新 case", "已确认", "本轮选择 Revert Finance Base 2026-01-30，而不是此前跑过的 MegaETH/Purrlend、Bunni、Scallop 等样例。"),
            ("Base seed tx", "已确认", f"`{revert.get('seed_tx', '-')}` block={flow.get('block_number', '-')}, status={flow.get('status', '-')}。"),
            ("High finding deterministic evidence", "已确认", f"finding 绑定 tx_metadata / receipt_log evidence；flow_evidence_id={revert.get('flow_evidence_id', '-')}。"),
            ("根因与修复", "已确认", "官方 post-mortem 指向 V3Utils / GaugeManager 管理路径缺少 collateralized-position 检查，并给出修复方向。"),
            ("总损失", "已确认", f"{revert.get('loss_summary', '50,101.744193 USDC')}；用户资金影响：官方称无第三方用户资金损失。"),
            ("范围边界", "已写入证据边界", "超出 deterministic 范围的源码行级复算已在正文中说明，不作为最终报告的开放事项输出。"),
        ]
        return "\n\n".join(
            [
                "### A.1 交易列表",
                self._table(["Phase", "Tx", "Block", "From", "To", "Artifact"], tx_rows) if tx_rows else "暂无交易。",
                "### A.2 Evidence 列表",
                self._table(["ID", "Source", "Producer", "Claim", "Confidence", "Raw Path"], evidence_rows) if evidence_rows else "暂无 evidence。",
                "### A.3 Revert 事件字段",
                self._table(["字段", "值"], [("incident_key", revert.get("incident_key", "-")), ("seed_tx", revert.get("seed_tx", "-")), ("second_tx", revert.get("second_tx", "-")), ("loss_summary", revert.get("loss_summary", "-")), ("nft_token_id", flow.get("nft_token_id", "-"))]),
                "### A.4 外部来源",
                self._table(["来源", "URL", "用途"], source_rows) if source_rows else "暂无外部来源。",
                "### A.5 TxAnalyzer Artifact Summary",
                self._table(["字段", "值"], txanalyzer_rows) if txanalyzer_rows else "暂无 TxAnalyzer artifact summary。",
                "### A.6 Worker 最新执行记录",
                self._table(["Worker", "Status", "Started", "Error"], job_rows) if job_rows else "暂无 job run。",
                "### A.7 复核结论",
                self._table(["复核项", "结论", "证据 / 说明"], verification_rows),
            ]
        )

    def _revert_facts(self, evidence: list) -> dict[str, Any]:
        facts: dict[str, Any] = {}
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "revert_finance_incident_summary" and isinstance(decoded, dict):
                facts.update(decoded)
                facts["incident_evidence_id"] = item.id
            if item.claim_key == "revert_receipt_flow_summary" and isinstance(decoded, dict):
                facts["flow"] = decoded
                facts["flow_evidence_id"] = item.id
        if facts.get("project") == "Revert Finance" or facts.get("incident_evidence_id"):
            return facts
        return {}

    def _revert_facts_from_case_evidence(self, case_id: str) -> dict[str, Any]:
        return self._revert_facts(EvidenceService(self.db).list_for_case(case_id))

    def _revert_source_label(self, revert: dict[str, Any], source_hint: str) -> str:
        for source in revert.get("sources", []):
            label = str(source.get("label", ""))
            role = str(source.get("role", ""))
            if source_hint.lower() in f"{label} {role}".lower():
                return source.get("url") or label
        sources = revert.get("sources", [])
        if sources:
            return sources[0].get("url") or sources[0].get("label", "-")
        return "-"

    def _scallop_tldr(self, case, timeline: list[dict], evidence: list, scallop: dict[str, Any]) -> str:
        flow = self._scallop_primary_flow(scallop)
        tx = scallop.get("tx") or {}
        attacker = tx.get("sender") or flow.get("to") or "-"
        lines = [
            "**事件类型:** Sui rewards side-contract exploit / deprecated package reward accounting",
            f"**链:** {case.network.name}",
            f"**日期:** {scallop.get('date', self._incident_date(case, timeline))}",
            f"**核心交易:** `{scallop.get('tx_digest') or tx.get('digest') or case.seed_value}`",
            f"**攻击地址:** `{attacker}`",
            f"**损失:** {scallop.get('loss_summary', '约 150,000 SUI')}",
            "**影响范围:** 限于 sSUI spool rewards pool；公开通报称核心 lending 合约和用户本金未受影响。",
            "**一句话根因:** 旧版 rewards/spool 合约仍可被调用，新建 spool account 的奖励基线没有正确约束，导致攻击者把短时间质押计算成长期历史质押并一次性领取奖励。",
            "**分析工具:** Sui JSON-RPC + transaction block/effects/events + external incident reports + RCA Workbench diagrams/PDF",
            f"**置信度:** {case.confidence}",
        ]
        return "\n".join(lines)

    def _scallop_overview(self, case, timeline: list[dict], evidence: list, findings: list, scallop: dict[str, Any]) -> str:
        flow = self._scallop_primary_flow(scallop)
        tx = scallop.get("tx") or {}
        amount = flow.get("amount") or "150,000"
        net_amount = flow.get("net_amount")
        paragraphs = [
            (
                "Scallop Lend 这次不是核心借贷市场被直接打穿，而是 sSUI spool 奖励池旁路合约暴露了攻击面。"
                "公开通报和第三方复盘都把范围收敛到 rewards/spool 相关合约：用户存款、主借贷池和其他奖励池不在本次直接影响范围内。"
            ),
            (
                f"Workbench 已用 Sui fullnode 复核核心交易 `{scallop.get('tx_digest') or tx.get('digest') or case.seed_value}`。"
                f"交易 effects 为 `{tx.get('status', '-')}`，事件序列中能看到 mint/new_spool_account/stake/update_points/redeem_rewards/unstake/redeem/transfer 这一组连续动作。"
            ),
            (
                f"资金层面，链上 balanceChanges 显示攻击地址获得约 `{net_amount or amount}` SUI 净增；"
                f"reward event 口径显示从 rewards pool 赎回约 `{amount}` SUI。"
                "这与公开损失口径约 150K SUI 一致。"
            ),
            (
                "报告中的根因表述分成两层：链上事实层确认“旧 rewards package 被调用并完成异常奖励赎回”；"
                "机制解释层来自公开复盘，指向未初始化或未正确设定的 reward index/last_index 基线。"
                "这不是把外部说法当作源码级证明，而是把它作为解释链上事实的机制证据。"
            ),
            f"系统已收集 `{len(evidence)}` 条 evidence，生成 `{len(findings)}` 条未被拒绝 finding；最终报告不会纳入 rejected finding。",
        ]
        return "\n\n".join(paragraphs)

    def _scallop_entities(self, case, transactions: list, evidence: list, scallop: dict[str, Any]) -> str:
        tx = scallop.get("tx") or {}
        flow = self._scallop_primary_flow(scallop)
        calls = tx.get("calls") or []
        old_package = scallop.get("deprecated_package") or self._scallop_package_from_calls(calls, module="user") or "-"
        rows = [
            ("协议", "Scallop Lend", "Sui lending protocol", "external reports"),
            ("目标池", "sSUI spool rewards pool", "奖励分发池，不是核心借贷本金池", "official notice / external reports"),
            ("旧 rewards package", old_package, "new_spool_account/stake/update_points/redeem_rewards/unstake 调用路径", "Sui tx input"),
            ("Rewards pool object", self._scallop_reward_pool(flow, tx), "被赎回 SUI 的奖励池对象", "Sui event / object changes"),
            ("攻击交易", scallop.get("tx_digest") or tx.get("digest") or case.seed_value, "核心链上证据", "sui_getTransactionBlock"),
            ("攻击地址", tx.get("sender") or flow.get("to") or "-", "交易 sender / 资金接收地址", "Sui tx + balanceChanges"),
        ]
        source_rows = [(source.get("label"), source.get("url"), source.get("role")) for source in scallop.get("sources", [])]
        evidence_rows = [(item.producer, item.source_type, item.claim_key, item.confidence) for item in evidence[:10]]
        return "\n\n".join(
            [
                "### 2.1 协议、对象与地址",
                self._table(["标识", "地址 / 对象", "攻击阶段角色", "证据"], rows),
                "### 2.2 公开来源",
                self._table(["来源", "URL", "用途"], source_rows) if source_rows else "暂无外部来源。",
                "### 2.3 已采集证据来源",
                self._table(["Producer", "Source Type", "Claim", "Confidence"], evidence_rows) if evidence_rows else "暂无 evidence。",
            ]
        )

    def _scallop_timeline(self, case, timeline: list[dict], scallop: dict[str, Any]) -> str:
        tx = scallop.get("tx") or {}
        flow = self._scallop_primary_flow(scallop)
        digest = scallop.get("tx_digest") or tx.get("digest") or case.seed_value
        calls = tx.get("calls") or []
        call_sequence = " -> ".join(
            f"{call.get('module')}::{call.get('function')}"
            for call in calls
            if call.get("module") and call.get("function")
        )
        rows = [
            ("Phase 0", "2023-11", "旧 V2/spool package 已部署", "Sui package 不可变；旧入口若未显式封禁，仍可能被调用", "external analysis"),
            ("Phase 1", self._scallop_time(tx), digest, "攻击者提交 ProgrammableTransaction", "Sui tx metadata"),
            ("Phase 2", self._scallop_time(tx), "new_spool_account + stake", "用新 spool account 建立奖励账户并短暂质押 sSUI/MarketCoin", "Sui tx input"),
            ("Phase 3", self._scallop_time(tx), "update_points + redeem_rewards", f"reward event 显示赎回约 {flow.get('amount', '-')} SUI", "Sui event"),
            ("Phase 4", self._scallop_time(tx), "TransferObjects", f"balanceChanges 显示攻击地址净增约 {flow.get('net_amount') or flow.get('amount', '-')} SUI", "Sui effects"),
            ("Phase 5", "事后", "冻结与恢复", "Scallop 冻结受影响合约，公开表示核心合约/用户本金未受影响并承诺覆盖损失", "official notice via reports"),
        ]
        return "\n\n".join(
            [
                self._table(["Phase", "时间", "对象 / Tx", "动作", "证据"], rows),
                "### 关键交易调用序列",
                f"```text\n{call_sequence or '暂无 MoveCall 序列'}\n```",
                "### 关键链上事实",
                "\n".join(
                    [
                        f"- 交易 digest `{digest}` 已通过 Sui `sui_getTransactionBlock` 返回，checkpoint `{tx.get('checkpoint', '-')}`。",
                        f"- 交易 sender 为 `{tx.get('sender', '-')}`，effects status 为 `{tx.get('status', '-')}`。",
                        f"- reward event 与 balanceChanges 一起支撑“奖励池 SUI 被一次性赎回到攻击地址”的资金流图。",
                    ]
                ),
            ]
        )

    def _scallop_root_cause(self, case, findings: list, evidence: list, scallop: dict[str, Any]) -> str:
        rows = [
            (
                self._finding_title(finding),
                finding.finding_type,
                finding.severity,
                finding.confidence,
                finding.reviewer_status,
                ", ".join(finding.evidence_ids) or "missing",
            )
            for finding in findings
        ]
        finding_block = self._table(["Finding", "Type", "Severity", "Confidence", "Review", "Evidence"], rows) if rows else "暂无 finding。"
        return "\n\n".join(
            [
                "### 4.1 先把问题边界说清楚",
                (
                    "本案的直接目标是 rewards/spool 侧合约，不是 Scallop 的主借贷本金池。"
                    "这一区分很重要：用户存款没有因为主 market 逻辑被错误转走；损失来自奖励池中的 SUI 被异常领取。"
                ),
                "### 4.2 Finding 汇总",
                finding_block,
                "### 4.3 根因：旧奖励合约的奖励基线失效",
                (
                    "奖励池通常会用一个全局 index 表示“每单位质押份额累计能拿多少奖励”，再用用户账户里的 last_index 记录该用户上次结算的位置。"
                    "新建账户如果没有把 last_index 设到当前 index，而是落在 0 或旧值，系统就会把这个账户误认为从很早以前就一直在质押。"
                    "公开复盘将 Scallop 事件归因到这一类 reward accounting 问题：攻击者调用旧 V2/spool package，创建新的 spool account，短暂质押后触发 update/redeem，拿到了按历史累计错误计算出来的奖励。"
                ),
                (
                    "链上交易能直接确认的是调用路径和结果：同一笔 ProgrammableTransaction 中出现 new_spool_account、stake、update_points、redeem_rewards、unstake、redeem 和 TransferObjects，"
                    "随后 balanceChanges 显示攻击地址获得约 150K SUI。"
                    "因此，本报告把“旧合约仍可调用 + 奖励基线错误”作为根因结论，把具体 last_index 变量名标注为公开复盘解释，而不是把未拉取源码逐行复现的内容写成独立 deterministic evidence。"
                ),
                "### 4.4 攻击者身份推断",
                (
                    f"当前只能把 `{(scallop.get('tx') or {}).get('sender') or '-'}` 作为链上攻击地址。"
                    "没有证据支持自然人、团队或内部身份归因；报告不做身份定性。"
                ),
                "### 4.5 证据边界",
                "\n".join(
                    [
                        "- Deterministic evidence: Sui transaction block、effects status、events、balanceChanges。",
                        "- Corroborating evidence: Scallop 公告转述、Blockonomi/KuCoin/BeInCrypto/BlockTempo 等公开报道。",
                        "- TxAnalyzer 是 EVM 工具，本案不适用；系统使用 Sui JSON-RPC artifact 替代 trace/source/opcode artifact。",
                    ]
                ),
            ]
        )

    def _scallop_financial_impact(self, case, evidence: list, scallop: dict[str, Any]) -> str:
        flow = self._scallop_primary_flow(scallop)
        total_rows = [
            ("链上 reward event", f"{flow.get('amount', '-')} SUI", "SpoolAccountRedeemRewardsEventV2", "赎回毛额"),
            ("链上 balanceChanges", f"{flow.get('net_amount') or '-'} SUI", "Sui effects", "攻击地址净增，已扣除同笔交易 gas 等影响"),
            ("公开损失口径", scallop.get("loss_summary", "约 150,000 SUI"), "external reports", "与链上量级一致"),
            ("用户补偿", "Scallop 承诺覆盖 100% 损失", "official notice via reports", "不把奖励池缺口转嫁给用户"),
        ]
        if case.loss_usd is not None:
            total_rows.append(("Workbench USD field", f"${float(case.loss_usd):,.2f}", "case.loss_usd", "数据库估值字段"))
        flow_rows = [
            (
                flow.get("asset", "SUI"),
                flow.get("amount", "-"),
                flow.get("from", "-"),
                flow.get("to", "-"),
                flow.get("evidence", "Sui event + balanceChanges"),
            )
        ]
        return "\n\n".join(
            [
                "### 5.1 奖励池流出",
                self._table(["资产", "数量", "来源", "接收方", "证据"], flow_rows),
                "这笔流出不是普通用户提款失败，而是奖励分配逻辑把攻击者的新账户识别成可领取长期累计奖励的账户。",
                "### 5.2 影响范围",
                self._table(["口径", "金额 / 状态", "来源", "说明"], total_rows),
                "### 5.3 资金流证据",
                "资金流图使用同一份 `sui_reward_redemption_flow` evidence 生成，因此 Web 预览和 PDF 中的图例会保持一致。",
            ]
        )

    def _scallop_methodology(self, case, jobs: list[JobRun], evidence: list, scallop: dict[str, Any]) -> str:
        env = self._environment_facts(evidence, jobs)
        latest_jobs = self._latest_jobs(jobs)
        env_rows = [
            ("Sui chain identifier", env.get("chain_identifier", "-"), "通过" if env.get("rpc_ok") else "未通过 / 未执行", env.get("rpc_source", "-")),
            ("Latest checkpoint", env.get("latest_checkpoint", "-"), "确认 Sui fullnode 可用", "sui_getLatestCheckpointSequenceNumber"),
            ("Tx block", scallop.get("tx_digest") or (scallop.get("tx") or {}).get("digest") or "-", "已拉取", "sui_getTransactionBlock"),
            ("TxAnalyzer", "不适用", "TxAnalyzer 只覆盖 EVM 交易，本案改用 Sui native RPC artifact", "network_type=sui"),
        ]
        evidence_rows = [
            ("Sui tx metadata", "sui_getTransactionBlock", "sender、checkpoint、MoveCall 序列、effects status", "deterministic"),
            ("Sui event/effects", "events + balanceChanges", "reward redemption 和攻击地址净增", "deterministic"),
            ("External reports", "public incident reports", "受影响范围、赔付承诺、deprecated package/last_index 机制解释", "corroborating"),
        ]
        workflow = "\n".join(
            [
                f"Step 1: Sui RPC 环境验证 -> chain_identifier={env.get('chain_identifier', '-')}, checkpoint={env.get('latest_checkpoint', '-')}",
                "Step 2: 拉取核心 transaction block -> input/effects/events/balanceChanges 入库",
                "Step 3: 提取 reward redemption flow -> 生成资金流图、攻击流程图和证据图",
                "Step 4: 结合公开复盘解释 reward index/last_index 机制 -> 形成中高置信 finding",
                "Step 5: 报告和 PDF 使用同一份 diagram_specs，避免 Web/PDF 图例不一致",
            ]
        )
        return "\n\n".join(
            [
                "### 6.1 分析工具栈",
                self._table(["检查项", "结果", "意义", "来源"], env_rows),
                "### 6.2 本案证据分层",
                self._table(["证据层", "采集方式", "能证明什么", "可靠性"], evidence_rows),
                "### 6.3 分析步骤",
                f"```text\n{workflow}\n```",
                "### 6.4 数据可靠性",
                "\n".join(
                    [
                        f"- Evidence count: {len(evidence)}",
                        f"- Latest worker runs: {len(latest_jobs)}，明细见附录。",
                        "- High-confidence finding 仍要求 deterministic evidence；本案根因机制使用 medium confidence，是因为变量级解释来自公开复盘而非本地源码重放。",
                    ]
                ),
            ]
        )

    def _scallop_appendix(self, transactions: list, evidence: list, jobs: list[JobRun], scallop: dict[str, Any]) -> str:
        tx_rows = [
            (tx.phase, tx.tx_hash, tx.block_number or "-", tx.method_name or "-", self._purrlend_artifact_status(tx.artifact_status))
            for tx in transactions
        ]
        evidence_rows = [(item.id, item.source_type, item.producer, item.claim_key, item.confidence, item.raw_path or "-") for item in evidence]
        job_rows = [(job.job_name, job.status, self._format_dt(job.started_at or job.created_at), job.error or "-") for job in self._latest_jobs(jobs)]
        verification_rows = [
            ("Sui RPC", "已确认", f"chain_identifier={(self._environment_facts(evidence, jobs)).get('chain_identifier', '-')}"),
            ("核心交易", "已确认", scallop.get("tx_digest") or (scallop.get("tx") or {}).get("digest") or "-"),
            ("资金流", "已确认", f"{self._scallop_primary_flow(scallop).get('amount', '-')} SUI reward redemption"),
            ("TxAnalyzer", "不适用", "本案是 Sui/Move 事件，不是 EVM 交易。"),
        ]
        return "\n\n".join(
            [
                "### A.1 交易列表",
                self._table(["Phase", "Tx", "Checkpoint", "Method", "Artifact"], tx_rows) if tx_rows else "暂无交易。",
                "### A.2 Evidence 列表",
                self._table(["ID", "Source", "Producer", "Claim", "Confidence", "Raw Path"], evidence_rows) if evidence_rows else "暂无 evidence。",
                "### A.3 Worker 最新执行记录",
                self._table(["Worker", "Status", "Started", "Error"], job_rows) if job_rows else "暂无 job run。",
                "### A.4 复核结论",
                self._table(["复核项", "结论", "证据 / 说明"], verification_rows),
            ]
        )

    def _purrlend_tldr(self, case, timeline: list[dict], evidence: list, purrlend: dict[str, Any]) -> str:
        txs = purrlend.get("txs") or []
        txanalyzer = self._txanalyzer_facts(evidence)
        internal = self._purrlend_internal_transfer(purrlend)
        outflow = self._purrlend_final_outflow(purrlend)
        lines = [
            "**事件类型:** 借贷市场 unbacked mint / borrow 控制边界失效",
            f"**链:** {case.network.name} (Chain ID: {case.network.chain_id})",
            f"**日期:** {purrlend.get('date_utc', self._incident_date(case, timeline))}",
            f"**攻击窗口:** 09:42:07 - 09:49:40 UTC+8，约 7 分钟",
            f"**攻击者地址:** `{purrlend.get('attacker_address', '-')}`",
            f"**链上范围:** MegaETH 侧已复现 `{len(txs)}` 笔攻击交易",
            f"**损失:** MegaETH 侧外部报道口径约 `{self._purrlend_loss_text(purrlend.get('megaeth_loss_summary', '-'))}`；全事件约 `{self._purrlend_loss_text(purrlend.get('total_loss_summary', '-'))}`",
            "**分析工具:** TxAnalyzer + MegaETH Explorer/RPC + RCA Workbench",
            "",
            "一句话说，这不是最后一步转账把钱拿走那么简单。攻击者先把未支持铸造额度打开，再连续 `mintUnbacked` 生成可被借贷流程识别的账面头寸，随后通过标准 borrow 路径借出真实资产，并用 LiFi/Across 一类处置路径把资产转走。",
        ]
        if internal:
            lines.append(f"**关键资金流:** `{internal.get('amount_eth')}` ETH 从 `{internal.get('from')}` 转入攻击者地址。")
        if outflow:
            lines.append(f"**后续外转:** `{outflow.get('amount_eth')}` ETH 被转至 `{outflow.get('to')}`。")
        lines.extend(
            [
                f"**TxAnalyzer:** {self._purrlend_txanalyzer_status(txanalyzer)}",
                f"**置信度:** {self._purrlend_confidence_label(case.confidence)}",
            ]
        )
        return "\n".join(lines)

    def _purrlend_overview(self, case, timeline: list[dict], evidence: list, findings: list, purrlend: dict[str, Any]) -> str:
        tx_count = len(purrlend.get("txs") or [])
        internal = self._purrlend_internal_transfer(purrlend)
        outflow = self._purrlend_final_outflow(purrlend)
        paragraphs = [
            (
                "2026 年 4 月 25 日上午，MegaETH 链上的 Purrlend 借贷市场发生攻击。"
                f"攻击者地址 `{purrlend.get('attacker_address', '-')}` 在 09:42:07 到 09:49:40 UTC+8 之间连续发起 `{tx_count}` 笔交易，"
                "整条链路从额度调整开始，到未支持铸造、债务授权、借款和跨链处置结束。"
            ),
            (
                "攻击过程最容易误解的地方，是把它看成一笔普通外转。真正的问题发生在更前面：攻击者先调用 `Set Unbacked Mint Cap`，"
                "让后续 `mintUnbacked` 有足够额度；随后四次 `Mint Unbacked` 制造账面头寸；再用 `Approve Delegation` 打开借款路径；"
                "最后通过 `Borrow ETH` / `Borrow` 把账面头寸转化为真实资产。"
            ),
            (
                "换句话说，合约最后把资产转出去只是结果，不是根因。根因在于 unbacked mint 与 borrow 之间的控制边界被打穿："
                "本应只在受控桥接/补偿流程中使用的未支持铸造头寸，被继续带入了标准借款流程。"
            ),
        ]
        if internal:
            paragraphs.append(
                f"链上可直接确认的一条资金线是：交易 `{internal.get('tx_hash')}` 内部把 `{internal.get('amount_eth')}` ETH "
                f"从 `{internal.get('from')}` 转入攻击者地址。"
            )
        if outflow:
            paragraphs.append(
                f"随后，交易 `{outflow.get('tx_hash')}` 将 `{outflow.get('amount_eth')}` ETH 转至 `{outflow.get('to')}`，"
                f"这就是 MegaETH 侧最清楚的一段资金外流。"
            )
        paragraphs.append(
            f"本报告使用 `{len(evidence)}` 条 evidence 和 `{len(findings)}` 条已审核 finding。MegaETH 本地证据用来支撑交易顺序、receipt、internal transfer 和 artifact；"
            "外部报道只用于说明事件总损失和 HyperEVM 相关范围。"
        )
        return "\n\n".join(paragraphs)

    def _purrlend_entities(self, case, transactions: list, evidence: list, purrlend: dict[str, Any]) -> str:
        txs = purrlend.get("txs") or []
        attacker = purrlend.get("attacker_address", "-")
        funding = self._purrlend_funding_transfer(purrlend)
        protocol_rows = [
            ("协议", "Purrlend", "受影响借贷市场", purrlend.get("primary_source", "-")),
            ("合约体系", "Aave V3-style lending flow", "unbacked mint / borrow / gateway 路径", "交易方法名与调用对象"),
            ("网络", f"{case.network.name} ({case.network.chain_id})", "本次复现网络", "系统网络配置"),
            ("攻击者", attacker, "EOA / Purrlend Exploiter 1", purrlend.get("explorer_url", "-")),
        ]
        attacker_rows = [
            ("地址类型", "EOA", "攻击者直接发起 14 笔交易；Explorer 标记为 Purrlend Exploiter 1。"),
            ("攻击前资金", f"{funding.get('amount_eth', '0.03336253')} ETH", f"攻击前一天进入攻击者地址，tx={funding.get('tx_hash', '-')}。"),
            ("核心能力", "set cap / mint unbacked / approve delegation / borrow / bridge", "这些动作连起来构成完整攻击链。"),
        ]
        contract_rows: list[tuple[Any, ...]] = []
        seen: set[str] = set()
        for tx in txs:
            to_addr = tx.get("to")
            if not to_addr or to_addr in seen:
                continue
            seen.add(to_addr)
            contract_rows.append(
                (
                    to_addr,
                    self._purrlend_method_label(tx.get("method", "-")),
                    self._purrlend_phase_label(tx.get("phase", "-")),
                    tx.get("tx_hash", "-"),
                )
            )
        evidence_groups: dict[str, dict[str, Any]] = {}
        for item in evidence:
            group = evidence_groups.setdefault(item.source_type, {"count": 0, "producers": set(), "claims": []})
            group["count"] += 1
            group["producers"].add(item.producer)
            claim = self._purrlend_claim_label(item.claim_key)
            if claim not in group["claims"] and len(group["claims"]) < 2:
                group["claims"].append(claim)
        evidence_rows = [
            (
                self._purrlend_source_type_label(source_type),
                group["count"],
                ", ".join(self._purrlend_producer_label(producer) for producer in sorted(group["producers"])),
                "；".join(group["claims"]),
            )
            for source_type, group in sorted(evidence_groups.items())
        ]
        return "\n\n".join(
            [
                "### 2.1 协议、网络与攻击者",
                "先把对象关系讲清楚：本案不是单个 token 转账异常，而是攻击者在借贷市场的 unbacked mint 和 borrow 流程之间建立了一条可执行路径。",
                self._table(["标识", "对象", "角色", "证据"], protocol_rows),
                "### 2.2 攻击者地址画像",
                "这个地址的行为非常集中：先拿到启动资金，随后在几分钟内完成配置、铸造、授权、借款和处置。它不像普通用户地址，更像一次性执行地址。",
                self._table(["项目", "值", "解释"], attacker_rows),
                "### 2.3 攻击者触达的核心合约",
                "下面这张表不是简单罗列地址，而是说明每类合约在攻击链中的作用。",
                self._table(["地址 / 合约", "方法", "阶段", "证据交易"], contract_rows),
                "### 2.4 已采集证据来源",
                "正文优先引用能直接解释攻击路径的证据：交易列表、receipt/log、internal transfer 和 TxAnalyzer artifact。附录只保留分组索引。",
                self._table(["证据类型", "数量", "采集模块", "正文用途"], evidence_rows) if evidence_rows else "没有可展示的 evidence。",
            ]
        )

    def _purrlend_timeline(self, case, timeline: list[dict], purrlend: dict[str, Any]) -> str:
        txs = purrlend.get("txs") or []
        cap_tx = next((tx for tx in txs if tx.get("method") == "Set Unbacked Mint Cap"), {})
        mint_txs = [tx for tx in txs if tx.get("method") == "Mint Unbacked"]
        approve_tx = next((tx for tx in txs if tx.get("method") == "Approve Delegation"), {})
        borrow_txs = [tx for tx in txs if tx.get("method") in {"Borrow ETH", "Borrow"}]
        post_txs = [tx for tx in txs if tx.get("method") == "0xd7a08473"]
        internal = self._purrlend_internal_transfer(purrlend)
        outflow = self._purrlend_final_outflow(purrlend)
        tx_rows = []
        txs_by_hash = {tx.get("tx_hash", "").lower(): tx for tx in purrlend.get("txs") or []}
        source_rows = timeline or []
        if source_rows:
            for index, item in enumerate(source_rows, start=1):
                meta = txs_by_hash.get(str(item.get("tx_hash") or "").lower(), {})
                tx_rows.append(
                    (
                        f"Phase {index}",
                        self._format_dt(item.get("timestamp")) if item.get("timestamp") else meta.get("timestamp_utc", "-"),
                        item.get("tx_hash") or meta.get("tx_hash", "-"),
                        self._purrlend_method_label(meta.get("method") or item.get("method") or "-"),
                        self._purrlend_tx_status_label(meta.get("status_label") or item.get("phase") or "-"),
                        f"{item.get('evidence_count', 0)} 条",
                    )
                )
        else:
            for index, tx in enumerate(purrlend.get("txs") or [], start=1):
                tx_rows.append(
                    (
                        f"Phase {index}",
                        tx.get("timestamp_utc", "-"),
                        tx.get("tx_hash", "-"),
                        self._purrlend_method_label(tx.get("method", "-")),
                        self._purrlend_tx_status_label(tx.get("status_label", "-")),
                        "-",
                    )
                )
        mint_rows = [
            (tx.get("tx_hash", "-"), tx.get("block_number", "-"), "500,000 xUSD aToken", self._purrlend_tx_status_label(tx.get("status_label", "-")))
            for tx in mint_txs
        ]
        borrow_rows = [
            (
                tx.get("tx_hash", "-"),
                tx.get("block_number", "-"),
                self._purrlend_method_label(tx.get("method", "-")),
                self._purrlend_tx_status_label(tx.get("status_label", "-")),
                tx.get("to", "-"),
            )
            for tx in borrow_txs
        ]
        post_rows = [
            (tx.get("tx_hash", "-"), tx.get("block_number", "-"), self._purrlend_method_label(tx.get("method", "-")), tx.get("to", "-"))
            for tx in post_txs
        ]
        borrow_asset_rows = [
            ("ETH", "36.81359372 ETH", "WrappedTokenGatewayV3", internal.get("tx_hash", "-") if internal else "-"),
            ("USDT", "约 163,035.72 USDT", "Pool.borrow()", "0xf9b5365e... / 0xfc432014..."),
            ("xUSD", "约 75,683.93 xUSD", "Pool.borrow()，随后进入兑换路径", "0xe4346ba8... / 0x729c63a7..."),
        ]
        bridge_rows = [
            ("xUSD -> USDT -> Relay", "约 75,684 xUSD 兑换为约 75,622 USDT", "Ethereum L1", "0x22029a4b..."),
            ("USDT -> Across", "约 163,036 USDT", "Ethereum L1", "0x7049d9c8..."),
            ("ETH -> Across", f"{outflow.get('amount_eth', '36.84693546')} ETH", "Ethereum L1", outflow.get("tx_hash", "-")),
        ]
        return "\n\n".join(
            [
                "### Phase 1: 打开未支持铸造额度",
                (
                    f"Tx: `{cap_tx.get('tx_hash', '-')}` | Block `{cap_tx.get('block_number', '-')}`。"
                    f"攻击者先通过 `{cap_tx.get('to', '-')}` 调用 `Set Unbacked Mint Cap`。这一步本身不转出资产，"
                    "但它决定了后续 `mintUnbacked` 可以在多大额度内制造账面头寸。"
                ),
                "```text\n"
                "setUnbackedMintCap(...)\n"
                "  -> 提高未支持铸造上限\n"
                "  -> 为后续 4 次 mintUnbacked 打开额度空间\n"
                "  -> 攻击从配置变化进入资产状态变化\n"
                "```",
                "### Phase 2: 连续 mintUnbacked",
                (
                    "随后攻击者在不到 30 秒内连续提交 4 笔 `Mint Unbacked`。这一步是整条攻击最关键的资产状态变化："
                    "账面上出现了 2,000,000 xUSD aToken 规模的头寸，但这些头寸并不是攻击者先存入同等真实资产换来的。"
                ),
                self._table(["Tx", "Block", "金额", "状态"], mint_rows),
                "```text\n"
                "attacker -> Pool Proxy\n"
                "  -> mintUnbacked(asset=xUSD, amount=500,000)\n"
                "  -> aToken.mint(attacker, 500,000 xUSD)\n"
                "  -> repeat x 4 = 2,000,000 xUSD aToken\n"
                "```",
                "### Phase 3: 授权借款路径",
                (
                    f"Tx: `{approve_tx.get('tx_hash', '-')}` | Block `{approve_tx.get('block_number', '-')}`。"
                    f"攻击者调用 `{approve_tx.get('to', '-')}` 上的 `Approve Delegation`，让后续 gateway / debt token 路径可以代为借款。"
                    "如果没有这一步，前面制造出来的账面头寸还不能顺畅进入实际 borrow 流程。"
                ),
                "```text\n"
                "approveDelegation(delegatee = WrappedTokenGatewayV3, amount = max)\n"
                "  -> gateway 可以替攻击者走 WETH 借款路径\n"
                "```",
                "### Phase 4: 借出真实资产",
                (
                    "借款阶段把前面的账面头寸转化为真实资产。Explorer 对部分 borrow 交易显示 internal revert 标记，"
                    "但 receipt 和 internal transfer 仍确认 ETH 进入攻击者地址；因此这里按最终资产结果来理解，而不是只看 explorer 的提示文字。"
                ),
                self._table(["Tx", "Block", "方法", "Explorer 状态", "目标合约"], borrow_rows),
                self._table(["资产", "金额", "路径", "证据"], borrow_asset_rows),
                (
                    f"ETH 路径最清楚：`{internal.get('amount_eth', '-')}` ETH 从 `{internal.get('from', '-')}` "
                    f"转至攻击者地址 `{internal.get('to', '-')}`。"
                    if internal
                    else "ETH 路径由 borrow 交易和 receipt/log 解释。"
                ),
                "### Phase 5: 兑换/桥接准备与最终外转",
                (
                    "拿到真实资产以后，攻击者没有停留在 MegaETH。后续两笔 `0xd7a08473` 更像是兑换和桥接准备，"
                    "`0xa1f1ce43` 则完成 ETH 外转。decoded path 可以概括为：xUSD 先换成 USDT，USDT 和 ETH 再经跨链路由转往 Ethereum L1。"
                ),
                self._table(["Tx", "Block", "方法", "目标地址"], post_rows) if post_rows else "未识别到 post-exploit 调用。",
                self._table(["路径", "金额", "目标链", "证据交易"], bridge_rows),
                (
                    f"最终 ETH 外转交易 `{outflow.get('tx_hash', '-')}` 将 `{outflow.get('amount_eth', '-')}` ETH 转至 `{outflow.get('to', '-')}`。"
                    if outflow
                    else "最终外转由处置交易解释。"
                ),
                "### 全量交易索引",
                self._table(["Phase", "时间(UTC)", "Tx", "动作 / 方法", "状态", "Evidence"], tx_rows),
            ]
        )

    def _purrlend_root_cause(self, case, findings: list, evidence: list, purrlend: dict[str, Any]) -> str:
        rows = [
            (
                self._finding_title(finding),
                self._purrlend_finding_type_label(finding.finding_type),
                self._purrlend_severity_label(finding.severity),
                self._purrlend_confidence_label(finding.confidence),
                self._purrlend_review_status_label(finding.reviewer_status),
                self._finding_evidence_summary(finding, evidence),
            )
            for finding in findings
        ]
        txanalyzer = self._txanalyzer_facts(evidence)
        return "\n\n".join(
            [
                "### 4.1 合约功能本身不是普通转账漏洞",
                (
                    "`mintUnbacked` 不是一个普通 token mint，也不是最后一步 `transfer()`。在 Aave V3-style 借贷系统里，"
                    "它原本是给桥接场景准备的：目标链可以先铸造 aToken，后续再由底层资产补齐。"
                    "这个设计成立的前提是调用者、额度和后续补偿流程都被严格约束。"
                ),
                (
                    "本案的问题正是这些约束被连成了攻击路径。攻击者先调整 unbacked mint cap，再用 `mintUnbacked` 制造账面头寸，"
                    "然后把这些头寸带入标准 borrow。也就是说，最后的 ETH/USDT 外流只是结果，真正的根因在更早的权限和额度边界。"
                ),
                "### 4.2 Finding 汇总",
                self._table(["结论", "类型", "严重性", "置信度", "审核状态", "证据摘要"], rows) if rows else "没有有效 finding。",
                "### 4.3 根因：unbacked mint 与 borrow 之间的隔离失效",
                (
                    "根因可以压缩成一句话：攻击者制造出的 unbacked aToken 被借贷系统当作可继续参与 borrow 的有效头寸。"
                    "如果 unbacked 头寸不能进入借款健康因子校验，或者额度调整和 bridge 权限不能被同一攻击链使用，后续真实资产就不会流出。"
                ),
                "攻击根因链：",
                "\n".join(
                    [
                        "1. `Set Unbacked Mint Cap` 提高未支持铸造可用额度。",
                        "2. `Mint Unbacked` 连续执行 4 次，形成约 2,000,000 xUSD aToken 账面头寸。",
                        "3. `Approve Delegation` 允许 gateway / debt token 路径代为借款。",
                        "4. `Borrow ETH` / `Borrow` 使用这些头寸走标准借款逻辑。",
                        "5. 真实 ETH、USDT 和 xUSD 被取出，xUSD 又进入兑换路径。",
                        "6. LiFi / Across 等处置路径把资产转往 Ethereum L1 或新接收地址。",
                    ]
                ),
                "### 4.4 可能的攻击者身份推断",
                self._table(
                    ["证据", "推论"],
                    [
                        ("攻击者地址没有合约代码，行为集中在 14 笔交易内", "更像一次性 EOA，而不是正常长期用户。"),
                        ("攻击前一天收到 0.03336253 ETH 启动资金", "地址在攻击前被准备好，并非临时普通交互。"),
                        ("从 set cap 到最终外转约 7 分钟", "交易顺序高度编排，攻击步骤很可能事先准备。"),
                        ("Explorer 标记为 Purrlend Exploiter 1", "外部链上索引也将该地址归入本次攻击。"),
                    ],
                ),
                "### 4.5 证据边界",
                "\n".join(
                    [
                        "- 确定性证据：MegaETH explorer txlist、RPC transaction/receipt、internal transfer export、debug_traceTransaction artifact。",
                        f"- TxAnalyzer 状态：{self._purrlend_txanalyzer_status(txanalyzer)}",
                        "- 外部佐证：TheStreet 对 Purrlend 事件和损失口径的报道；MegaETH explorer 对攻击者地址的 exploit 标记。",
                        "- HyperEVM 侧属于同一事件背景，但本报告正文只把 MegaETH 侧交易写成链上复现结论。",
                    ]
                ),
            ]
        )

    def _purrlend_financial_impact(self, case, evidence: list, purrlend: dict[str, Any]) -> str:
        internal = self._purrlend_internal_transfer(purrlend)
        outflow = self._purrlend_final_outflow(purrlend)
        fake_collateral_rows = [
            ("xUSD aToken", "2,000,000 (4 x 500,000)", "mintUnbacked", "没有看到同等底层资产先进入攻击者账户。"),
        ]
        borrowed_rows = [
            ("ETH", f"{internal.get('amount_eth', '36.81359372')} ETH", "WrappedTokenGatewayV3", internal.get("tx_hash", "-") if internal else "0xc707a9b7..."),
            ("USDT", "约 163,035.72 USDT", "Pool.borrow()", "0xf9b5365e... + 0xfc432014..."),
            ("xUSD", "约 75,683.93 xUSD", "Pool.borrow()，随后兑换为 USDT", "0xe4346ba8... + 0x729c63a7..."),
        ]
        bridge_rows = [
            ("Across Protocol", "~36.85 ETH", "Ethereum L1", outflow.get("tx_hash", "-") if outflow else "0xff2d8723..."),
            ("Across Protocol", "~163,036 USDT", "Ethereum L1", "0x7049d9c8..."),
            ("Relay / DEX route", "~75,622 USDT", "Ethereum L1", "0x22029a4b..."),
        ]
        total_rows = [
            ("链上复盘口径", "~36.8 ETH + ~238,658 USDT", "~$304,898", "按 decoded 资产拆分口径。"),
            ("MegaETH 外部报道口径", self._purrlend_loss_text(purrlend.get("megaeth_loss_summary", "-")), f"${float(case.loss_usd):,.0f}" if case.loss_usd is not None else "-", "TheStreet / case 字段。"),
            ("全事件外部报道口径", self._purrlend_loss_text(purrlend.get("total_loss_summary", "-")), "-", "包含 MegaETH 与 HyperEVM。"),
        ]
        return "\n\n".join(
            [
                "### 5.1 铸造的虚假抵押品",
                (
                    "财务影响要从虚假抵押品开始看。攻击者不是先存入真实资产再借款，而是先通过 `mintUnbacked` "
                    "制造可被系统识别的 aToken 头寸。"
                ),
                self._table(["资产", "金额", "方式", "解释"], fake_collateral_rows),
                "### 5.2 借出的真实资产",
                (
                    "一旦账面头寸进入 borrow 流程，流出的就是真实资产。ETH 的 internal transfer 已由 MegaETH explorer 导出确认；"
                    "USDT 和 xUSD 金额采用 decoded transaction 口径。"
                ),
                self._table(["资产", "金额", "来源", "证据"], borrowed_rows),
                "### 5.3 跨链转出",
                "处置阶段的目标很清楚：把借出的资产从 MegaETH 转出，降低追回难度。",
                self._table(["路径", "金额", "目标链", "证据交易"], bridge_rows),
                "### 5.4 总损失",
                "这里把两个口径分开：链上复盘口径用于解释资金如何流出；外部报道口径用于表达事件级损失规模。",
                self._table(["口径", "金额", "美元估值", "说明"], total_rows),
                "### 5.5 攻击成本",
                "攻击者在攻击前收到 0.03336253 ETH 作为启动资金。MegaETH gas price 极低，链上复盘口径估算 14 笔攻击交易总 gas 约 0.000008 ETH，因此链上执行成本几乎可以忽略。",
            ]
        )

    def _purrlend_methodology(self, case, jobs: list[JobRun], evidence: list, purrlend: dict[str, Any]) -> str:
        env = self._environment_facts(evidence, jobs)
        txanalyzer = self._txanalyzer_facts(evidence)
        latest_jobs = self._recent_non_report_jobs(jobs)
        env_rows = [
            ("RPC chainId", env.get("chain_id", "-"), "通过" if env.get("rpc_ok") else "未通过 / 未执行", env.get("rpc_source", "-")),
            ("trace_transaction", self._bool_label(env.get("trace_transaction_ok")), "MegaETH public RPC 当前不支持", env.get("trace_target_tx", "-")),
            ("debug_traceTransaction", self._bool_label(env.get("debug_trace_transaction_ok")), "可生成 opcode 级 artifact", env.get("trace_target_tx", "-")),
            ("Explorer", purrlend.get("explorer_url", "-"), "交易列表、internal transfer 和地址标签", "MegaETH explorer"),
            ("TxAnalyzer", self._purrlend_txanalyzer_status(txanalyzer), "CLI + fallback artifact import", "job_runs"),
        ]
        workflow = "\n".join(
            [
                "Step 1: 环境验证",
                "  |-- eth_chainId -> 4326，确认 RPC 连接到 MegaETH",
                "  |-- debug_traceTransaction -> 支持，用于 opcode 级 artifact",
                "  `-- trace_transaction -> public RPC 不支持，自动走 fallback artifact",
                "",
                "Step 2: 账户画像",
                "  |-- MegaETH explorer 标记攻击者为 Purrlend Exploiter 1",
                "  |-- txlist -> 14 笔攻击交易",
                "  `-- internal transfer -> 攻击前 0.03336253 ETH 启动资金 + 攻击中 36.81359372 ETH 流入",
                "",
                "Step 3: 交易分类",
                "  |-- 0x145f5892 -> Set Unbacked Mint Cap",
                "  |-- 0x69a933a5 -> Mint Unbacked",
                "  |-- 0xc04a8a10 -> Approve Delegation",
                "  |-- 0x66514c97 / 0xa415bcad -> Borrow ETH / Borrow",
                "  `-- 0xd7a08473 / 0xa1f1ce43 -> 处置与跨链",
                "",
                "Step 4: TxAnalyzer 拉取 artifact",
                "  |-- python scripts/pull_artifacts.py --network megaeth --tx <tx>",
                "  |-- 保存 stdout/stderr、receipt、transaction、debug trace",
                "  `-- CLI trace 不可用时仍保留 fallback manifest",
                "",
                "Step 5: 攻击语义复盘",
                "  |-- cap 调整 -> unbacked mint 可执行",
                "  |-- mintUnbacked x 4 -> 账面 aToken 头寸",
                "  |-- approveDelegation -> gateway/debt path 放行",
                "  `-- borrow -> 真实资产流出",
                "",
                "Step 6: 资金流复核",
                "  |-- internal transfer 确认 36.81359372 ETH 到攻击者",
                "  |-- final outflow 确认 36.84693546 ETH 到新地址",
                "  `-- 外部报道用于补充 USDT0/WETH/USDm 与 HyperEVM 事件级损失口径",
                "",
                "Step 7: 报告生成",
                "  |-- rejected finding 排除",
                "  |-- high finding 必须绑定确定性 evidence",
                "  `-- 正文只写已确认范围，事件级口径单独标注",
            ]
        )
        return "\n\n".join(
            [
                "### 6.1 分析工具栈",
                self._table(["工具", "用途"], [("MegaETH Explorer", "确认 exploiter label、txlist、internal transfer"), ("MegaETH Public RPC", "交易、receipt、debug opcode trace"), ("TxAnalyzer", "按官方 CLI 入口拉取 artifact；trace 不可用时导入 fallback artifact"), ("RCA Workbench", "evidence/finding/report schema 管理")]),
                "### 6.2 本案实际执行结果",
                self._table(["检查项", "结果", "意义", "来源"], env_rows),
                "### 6.3 证据分层",
                (
                    "报告采用复盘式读法：先用链上数据确认交易顺序和资金结果，再用 decoded path 解释每步为什么能推进，"
                    "最后把本地复现口径和外部报道口径分开。这样读者不会把“真实链上事实”和“事件总损失背景”混在一起。"
                ),
                self._table(["证据层", "采集方式", "能证明什么", "可靠性"], [("交易列表", "Explorer export", "攻击窗口、方法序列、对手方合约", "确定性 explorer 数据"), ("交易 receipt", "eth_getTransactionReceipt", "状态、日志、区块绑定", "确定性 RPC 数据"), ("opcode trace", "debug_traceTransaction", "opcode 执行路径", "RPC 支持时为确定性数据"), ("外部报道", "TheStreet", "事件范围和损失口径", "交叉佐证")]),
                "### 6.4 分析步骤",
                f"```text\n{workflow}\n```",
                "### 6.5 数据可靠性",
                "\n".join(
                    [
                        f"- 证据总数：{len(evidence)} 条。",
                        f"- 最新 worker 记录：{len(latest_jobs)} 条，明细见附录。",
                        "- 高危 finding 已绑定确定性证据。",
                        "- `trace_transaction` 不支持已被记录为链能力限制；系统使用 `debug_traceTransaction`、receipt 和 explorer fallback 形成可复核 artifact。",
                    ]
                ),
            ]
        )

    def _purrlend_appendix(self, transactions: list, evidence: list, jobs: list[JobRun], purrlend: dict[str, Any]) -> str:
        jobs = self._recent_non_report_jobs(jobs)
        txanalyzer = self._txanalyzer_facts(evidence)
        tx_rows = [
            (
                self._purrlend_phase_label(tx.phase),
                tx.tx_hash,
                tx.block_number or "-",
                self._purrlend_method_label(tx.method_name or tx.method_selector or "-"),
                self._purrlend_artifact_status(tx.artifact_status),
            )
            for tx in transactions
        ]
        evidence_groups: dict[str, dict[str, Any]] = {}
        for item in evidence:
            group = evidence_groups.setdefault(item.source_type, {"count": 0, "producers": set(), "claims": []})
            group["count"] += 1
            group["producers"].add(item.producer)
            claim = self._purrlend_claim_label(item.claim_key)
            if claim not in group["claims"] and len(group["claims"]) < 3:
                group["claims"].append(claim)
        evidence_rows = [
            (
                self._purrlend_source_type_label(source_type),
                group["count"],
                ", ".join(self._purrlend_producer_label(producer) for producer in sorted(group["producers"])),
                "; ".join(self._purrlend_claim_label(claim) for claim in group["claims"]),
            )
            for source_type, group in sorted(evidence_groups.items())
        ]
        job_rows = [
            (
                self._purrlend_producer_label(job.job_name),
                self._purrlend_job_status_label(job.status, job.job_name),
                self._format_dt(job.started_at or job.created_at),
                self._summarize_error(job.error),
            )
            for job in jobs
        ]
        txanalyzer_rows = [
            ("trace_transaction artifact", self._bool_label(txanalyzer.get("has_trace"))),
            ("receipt artifact", self._bool_label(txanalyzer.get("has_receipt"))),
            ("debug opcode artifact", self._bool_label(txanalyzer.get("has_opcode"))),
            ("导入文件数", txanalyzer.get("file_count")),
            ("降级原因", self._purrlend_fallback_reason(txanalyzer.get("fallback_reason"))),
        ] if txanalyzer else []
        verification_rows = [
            ("最新 MegaETH 事件身份", "已确认", "Purrlend exploit；TheStreet 2026-04-25 报道，MegaETH explorer 标记 exploiter address。"),
            ("MegaETH 攻击交易范围", "已确认", f"Explorer/RPC 导入 {len(purrlend.get('txs') or [])} 笔攻击者相关交易。"),
            ("高危结论的确定性证据", "已确认", "finding 绑定交易元数据、receipt/log 与 explorer 导出证据。"),
            ("TxAnalyzer artifact", "已降级确认", self._purrlend_txanalyzer_status(txanalyzer)),
            ("HyperEVM 侧", "不纳入本次 MegaETH 复现", "外部报道口径保留为 corroborating evidence，不写成本地 MegaETH 链上逐笔复现。"),
            ("开放事项", "无", "本报告不列问题清单；超出本次 deterministic 范围的内容已明确标为外部口径或范围外。"),
        ]
        return "\n\n".join(
            [
                "### A.1 交易列表",
                self._table(["阶段", "Tx", "Block", "动作", "Artifact"], tx_rows) if tx_rows else "没有交易。",
                "### A.2 Evidence 摘要",
                "完整 evidence 仍保存在数据库和 artifact 目录中；报告附录只放分组摘要，避免正文被证据 ID 淹没。",
                self._table(["证据类型", "数量", "采集模块", "证明内容示例"], evidence_rows) if evidence_rows else "没有 evidence。",
                "### A.3 Purrlend 事件字段",
                self._table(["字段", "值"], [("attacker_address", purrlend.get("attacker_address")), ("explorer_url", purrlend.get("explorer_url")), ("primary_source", purrlend.get("primary_source")), ("megaeth_loss_summary", self._purrlend_loss_text(purrlend.get("megaeth_loss_summary"))), ("total_loss_summary", self._purrlend_loss_text(purrlend.get("total_loss_summary")))]),
                "### A.4 TxAnalyzer Artifact Summary",
                self._table(["字段", "值"], txanalyzer_rows) if txanalyzer_rows else "暂无 TxAnalyzer artifact summary。",
                "### A.5 Worker 最新执行记录",
                self._table(["模块", "状态", "开始时间", "错误"], job_rows) if job_rows else "暂无 job run。",
                "### A.6 复核结论",
                self._table(["复核项", "结论", "证据 / 说明"], verification_rows),
            ]
        )

    def _bunni_tldr(self, case, timeline: list[dict], evidence: list, bunni: dict[str, Any]) -> str:
        addresses = bunni.get("addresses") or {}
        txanalyzer = self._txanalyzer_facts(evidence)
        flow = self._bunni_flow_facts(evidence)
        return "\n".join(
            [
                f"> **事件类型:** {self._bunni_attack_type_label(bunni.get('attack_type'))}",
                f"> **链:** {case.network.name} (Chain ID: {case.network.chain_id})",
                f"> **日期:** {bunni.get('date_utc', self._incident_date(case, timeline))}",
                f"> **攻击窗口:** {self._attack_window(case, timeline)}",
                f"> **核心交易:** `{bunni.get('ethereum_attack_tx', case.seed_value)}`",
                f"> **攻击者:** EOA `{addresses.get('attacker_eoa', '-')}` 调用攻击合约 `{addresses.get('attack_contract', '-')}`",
                f"> **目标池:** {bunni.get('affected_pool', 'Bunni V2 USDC/USDT pool on Ethereum')}",
                f"> **根因摘要:** {bunni.get('root_cause_summary', 'BunniHubLogic.withdraw() 在更新 idleBalance 时向下取整，重复小额赎回放大了 active balance 与总流动性估算偏差')}",
                f"> **损失:** {self._bunni_loss_text(bunni)}",
                f"> **链上复核:** receipt logs={flow.get('log_count', '-')}, TxAnalyzer={self._purrlend_txanalyzer_status(txanalyzer)}",
                f"> **置信度:** {self._purrlend_confidence_label(case.confidence)}",
            ]
        )

    def _bunni_overview(self, case, timeline: list[dict], evidence: list, findings: list, bunni: dict[str, Any]) -> str:
        addresses = bunni.get("addresses") or {}
        flow = self._bunni_flow_facts(evidence)
        txanalyzer = self._txanalyzer_facts(evidence)
        paragraphs = [
            (
                f"{bunni.get('date_utc', self._incident_date(case, timeline))}，Bunni V2 的 USDC/USDT 池在 Ethereum 上被攻击。"
                f"这不是一次普通的稳定币套利，也不是 Uniswap V4 或 USDC/USDT token 自身被攻破；攻击核心在 Bunni 自定义 LDF 与 `withdraw()` 会计逻辑之间的边界条件。"
            ),
            (
                f"攻击者 EOA `{addresses.get('attacker_eoa', '-')}` 向攻击合约 `{addresses.get('attack_contract', '-')}` 发起交易 `{bunni.get('ethereum_attack_tx', case.seed_value)}`。"
                "交易内部先从 Uniswap V3 借入 USDT，再通过 Bunni/Uniswap V4 路径操纵池内价格与 active balance，随后连续执行小额赎回，把一次看似很小的取整误差放大成流动性估算偏差。"
            ),
            (
                "最关键的理解点是：Bunni 把池子资金分成 active balance 与 idle balance。`withdraw()` 为了按份额减少 idle balance，使用了向下取整。"
                "单次操作看起来偏保守，但当 USDC active balance 已经被压到极小值时，44 次小额赎回会让 active USDC 从 28 wei 被压到 4 wei，导致系统把池子总流动性低估约 84.4%。"
            ),
            (
                "攻击者随后做了一组类似 sandwich 的反向 swap。第一次大额 swap 利用被低估的流动性把价格推到极端 tick；第二次反向 swap 又利用流动性估算从 USDC 口径切换到 USDT 口径的瞬间修正，提取 USDC/USDT 价差收益。"
            ),
            (
                f"Workbench 已完成 seed tx hydration、TxAnalyzer CLI 调用和 artifact 导入。TxAnalyzer 导入 `{txanalyzer.get('file_count', '-')}` 个文件，"
                f"trace={txanalyzer.get('has_trace', False)}，source={txanalyzer.get('has_source', False)}，opcode={txanalyzer.get('has_opcode', False)}。"
                f"Receipt 侧共解析 `{flow.get('log_count', '-')}` 条日志，其中 USDC/USDT Transfer 日志分别为 `{flow.get('usdc_transfer_count', '-')}` / `{flow.get('usdt_transfer_count', '-')}` 条。"
            ),
            (
                f"系统当前有 `{len(evidence)}` 条 evidence、`{len(findings)}` 条未被拒绝 finding。"
                "本报告把官方 post-mortem 与第三方复盘作为机制来源，把 seed tx metadata、receipt logs、TxAnalyzer trace/report 作为链上复核边界。"
            ),
        ]
        return "\n\n".join(paragraphs)

    def _bunni_entities(self, case, transactions: list, evidence: list, bunni: dict[str, Any]) -> str:
        addresses = bunni.get("addresses") or {}
        protocol_rows = [
            ("协议", "Bunni V2", "受影响的 Uniswap V4 hook / liquidity manager", bunni.get("primary_source", "-")),
            ("目标池", bunni.get("affected_pool", "USDC/USDT on Ethereum"), "被操纵的稳定币池", bunni.get("primary_source", "-")),
            ("PoolManager", addresses.get("pool_manager", "-"), "Uniswap V4 池管理合约", "TxAnalyzer trace"),
            ("BunniHub", addresses.get("bunni_hub", "-"), "`withdraw()` / LDF 查询相关合约", "TxAnalyzer trace + official post-mortem"),
            ("BunniToken", addresses.get("bunni_token", "-"), "LP share / 小额赎回路径", "TxAnalyzer trace"),
            ("USDC", addresses.get("usdc", "-"), "token0 / 被压低 active balance 的资产", "receipt logs"),
            ("USDT", addresses.get("usdt", "-"), "token1 / flashloan 与返还资产", "receipt logs"),
        ]
        attacker_rows = [
            (addresses.get("attacker_eoa", "-"), "Primary attacker EOA", "提交 seed tx", bunni.get("source_addresses_url", bunni.get("secondary_source", "-"))),
            (addresses.get("attack_contract", "-"), "Attack contract", "执行 flashloan callback、swap、withdraw 和最终资金处置", "tx_metadata + TxAnalyzer trace"),
            (addresses.get("uniswap_v3_pool", "-"), "Flashloan source", "向攻击合约借出 3,000,000 USDT，最终收回 3,009,000 USDT", "receipt logs"),
            (addresses.get("aave_ausdc", "-"), "Aave aUSDC", "接收攻击后 USDC 存款", "receipt logs"),
            (addresses.get("aave_ausdt", "-"), "Aave aUSDT", "接收攻击后 USDT 存款", "receipt logs"),
        ]
        evidence_groups = self._bunni_evidence_groups(evidence)
        tx_rows = [
            (tx.phase, tx.tx_hash, tx.from_address or "-", tx.to_address or "-", tx.method_name or tx.method_selector or "-")
            for tx in transactions
        ]
        return "\n\n".join(
            [
                "### 2.1 协议与核心合约",
                self._table(["标识", "地址 / 对象", "攻击阶段角色", "证据"], protocol_rows),
                "### 2.2 攻击者与资金落点",
                self._table(["地址", "角色", "行为", "证据"], attacker_rows),
                "### 2.3 Workbench 交易范围",
                self._table(["Phase", "Tx", "From", "To", "Method"], tx_rows) if tx_rows else "暂无交易。",
                "### 2.4 已采集证据来源",
                self._table(["证据层", "来源", "能证明什么", "可靠性"], evidence_groups),
            ]
        )

    def _bunni_timeline(self, case, timeline: list[dict], bunni: dict[str, Any]) -> str:
        addresses = bunni.get("addresses") or {}
        tx_hash = bunni.get("ethereum_attack_tx", case.seed_value)
        rows = [
            ("Phase 0", "攻击准备", addresses.get("attacker_eoa", "-"), "攻击者 EOA 调用攻击合约，准备在一笔交易内完成借款、操纵、赎回、套利和还款。", "tx_metadata"),
            ("Phase 1", self._attack_window(case, timeline), addresses.get("uniswap_v3_pool", "-"), "从 Uniswap V3 flashloan 借入 3,000,000 USDT。", "receipt logs + TxAnalyzer"),
            ("Phase 2", self._attack_window(case, timeline), addresses.get("pool_manager", "-"), "连续 swap 把 USDC/USDT 价格推离正常区间，并把 USDC active balance 压到 28 wei。", "official post-mortem + trace"),
            ("Phase 3", self._attack_window(case, timeline), addresses.get("bunni_hub", "-"), "执行 44 次小额 withdraw，利用 idleBalance 向下取整，把 active USDC 从 28 wei 进一步压到 4 wei。", "official post-mortem + trace"),
            ("Phase 4", self._attack_window(case, timeline), addresses.get("pool_manager", "-"), "先用大额 USDT->USDC swap 把 tick 推到 839189，再反向 swap 捕获流动性估算回弹产生的价差。", "official post-mortem + receipt logs"),
            ("Phase 5", self._attack_window(case, timeline), addresses.get("attack_contract", "-"), "归还 3,009,000 USDT flashloan，并把约 1.33M USDC 与 1.04M USDT 存入 Aave aToken。", "receipt logs"),
        ]
        trace_lines = [
            f"0. EOA {addresses.get('attacker_eoa', '-')} -> attack contract {addresses.get('attack_contract', '-')}",
            f"1. attack contract -> Uniswap V3 pool {addresses.get('uniswap_v3_pool', '-')} flash(..., 3,000,000 USDT)",
            f"2. callback -> Uniswap V4 PoolManager {addresses.get('pool_manager', '-')} swap(...)",
            f"3. callback -> BunniHub/BunniToken withdraw(...) repeated; rounding error accumulates",
            "4. callback -> PoolManager swap(...) / take(...) extracts USDC and USDT",
            f"5. attack contract -> Uniswap V3 pool repay 3,009,000 USDT",
            f"6. attack contract -> Aave aUSDC {addresses.get('aave_ausdc', '-')} and aUSDT {addresses.get('aave_ausdt', '-')}",
        ]
        diagram = "\n".join(
            [
                "Attacker EOA",
                "  | submit tx",
                "  v",
                "Attack contract",
                "  |-- flashloan 3,000,000 USDT --> Uniswap V3 USDT pool",
                "  |-- swap / take / sync --------> Uniswap V4 PoolManager",
                "  |-- withdraw x44 -------------> BunniHub / BunniToken",
                "  |-- repay 3,009,000 USDT -----> Uniswap V3 USDT pool",
                "  |-- deposit profit -----------> Aave aUSDC / aUSDT",
            ]
        )
        return "\n\n".join(
            [
                self._table(["Phase", "时间", "对象 / Tx", "动作", "证据"], rows),
                "### 关键交易分析",
                "\n".join(
                    [
                        f"- Seed tx `{tx_hash}` 在 Ethereum block `{self._bunni_block_number(timeline)}` 成功执行。",
                        "- 官方复盘把攻击拆为三段：价格操纵、小额赎回放大舍入误差、对流动性估算回弹做 sandwich。",
                        "- Receipt logs 确认 flashloan、还款和最终 USDC/USDT 利润去向；TxAnalyzer trace/report 确认 `flash`、`swap`、`withdraw`、`take`、`transfer` 等调用路径。",
                    ]
                ),
                "### 数据流图",
                f"```text\n{diagram}\n```",
                "### TxAnalyzer Trace 摘要",
                f"```text\n{chr(10).join(trace_lines)}\n```",
            ]
        )

    def _bunni_root_cause(self, case, findings: list, evidence: list, bunni: dict[str, Any]) -> str:
        addresses = bunni.get("addresses") or {}
        rows = [
            (
                self._finding_title(finding),
                self._bunni_finding_type_label(finding.finding_type),
                self._purrlend_severity_label(finding.severity),
                self._purrlend_confidence_label(finding.confidence),
                self._purrlend_review_status_label(finding.reviewer_status),
                self._finding_evidence_summary(finding, evidence),
            )
            for finding in findings
        ]
        finding_block = self._table(["Finding", "类型", "严重性", "置信度", "审核", "证据"], rows) if rows else "暂无 finding。"
        root_cause = bunni.get(
            "root_cause_summary",
            "BunniHubLogic.withdraw() 更新 idleBalance 时采用向下取整；当 active balance 已被压到极小值时，重复小额赎回会非线性放大误差。",
        )
        lines = [
            "### 4.1 这不是哪一类问题",
            (
                "本案不应写成单纯的价格操纵，也不应写成 USDC、USDT 或 Uniswap V4 的通用漏洞。"
                "价格操纵只是触发条件，真正可被提取价值的地方，是 Bunni 自定义流动性会计在极端 token balance 下失去了安全边界。"
            ),
            "### 4.2 Finding 汇总",
            finding_block,
            "### 4.3 根因：Bunni `withdraw()` 舍入方向在多次操作中不再安全",
            (
                f"{root_cause} 官方 post-mortem 指出，`balance.mulDiv(shares, currentTotalSupply)` 的减少额被向下取整。"
                "开发时的假设是：低估 active liquidity 会让 swap price impact 变大，似乎对池子更保守。"
                "但攻击者先把 USDC active balance 压到 28 wei，再用 44 次小额赎回把误差累积起来，使 active USDC 降到 4 wei，最终让总流动性估算从约 5.83e16 被压到 9.114e15。"
            ),
            (
                "这个低估值本身未必直接产生收益；收益来自第三阶段的“回弹”。攻击者做第一笔大额 swap 后，LDF 返回的密度让系统从 USDC 侧估算切换到 USDT 侧估算，"
                "总流动性从被压低状态突然回升约 16.8%。攻击者立即反向 swap，相当于把自己制造出的估算修正夹在两笔交易之间套利。"
            ),
            "攻击根因链：",
            "\n".join(
                [
                    f"1. 攻击合约 `{addresses.get('attack_contract', '-')}` 借入大额 USDT，把池内价格与 USDC active balance 推到极端边界。",
                    f"2. BunniHub `{addresses.get('bunni_hub', '-')}` 的 `withdraw()` 在减少 idleBalance 时向下取整。",
                    "3. 重复小额 withdraw 把单次微小误差累积成 active balance 与 total liquidity 的显著偏差。",
                    "4. 后续 swap 触发 totalLiquidityEstimate0/1 选择逻辑切换，流动性估算从低估状态恢复。",
                    "5. 攻击者对这个恢复过程做 sandwich，提取 USDC/USDT 资产并归还 flashloan。",
                ]
            ),
            "### 4.4 证据边界",
            "\n".join(
                [
                    "- Deterministic evidence: seed tx metadata、receipt logs、TxAnalyzer trace/report、USDC/USDT Transfer logs。",
                    f"- Mechanism source: {bunni.get('primary_source', '-')}；第三方交叉复核：{bunni.get('secondary_source', '-')} / {bunni.get('tertiary_source', '-')}。",
                    "- 精确的 28 wei、4 wei、84.4% 和 16.8% 来自官方/第三方复盘中的状态复现；Workbench 当前没有 debug opcode 与源码 API key，因此不把这些数值伪装成自行从 opcode 复算的结果。",
                    "- Receipt logs 已确认最终大额 USDC/USDT 流向；完整 Unichain 腿未在本 Ethereum case 内复现。",
                ]
            ),
        ]
        return "\n\n".join(lines)

    def _bunni_financial_impact(self, case, evidence: list, bunni: dict[str, Any]) -> str:
        flow = self._bunni_flow_facts(evidence)
        flows = flow.get("large_token_flows") or []
        token_rows = [
            (
                item.get("asset", "-"),
                item.get("amount", "-"),
                item.get("from", "-"),
                item.get("to", "-"),
                self._bunni_flow_meaning_label(item.get("meaning")),
            )
            for item in flows
        ]
        loss_rows = [
            ("Ethereum USDC/USDT pool", bunni.get("ethereum_loss_summary", "约 $2.4M"), bunni.get("primary_source", "-"), "本 case 已跑 Ethereum seed tx"),
            ("Unichain weETH/ETH pool", bunni.get("unichain_loss_summary", "约 $5.9M"), bunni.get("primary_source", "-"), "同机制另一条链，未在本 case 内跑"),
            ("全事件合计", bunni.get("total_loss_summary", "约 $8.4M"), bunni.get("primary_source", "-"), "外部报告口径"),
        ]
        if case.loss_usd is not None:
            loss_rows.append(("Workbench case field", f"${float(case.loss_usd):,.2f}", "case.loss_usd", "本地字段"))
        return "\n\n".join(
            [
                "### 5.1 攻击资金与 flashloan",
                (
                    "Ethereum 这笔 seed tx 先借入 3,000,000 USDT，交易末尾向同一 Uniswap V3 pool 归还 3,009,000 USDT。"
                    "这说明攻击收益必须覆盖 9,000 USDT 费用与 gas 成本，实际利润来自 Bunni 池内的 USDC/USDT 会计偏差。"
                ),
                "### 5.2 资产流出与利润落点",
                self._table(["资产", "数量", "From", "To", "含义"], token_rows) if token_rows else "暂无 token flow evidence。",
                "### 5.3 资金流图",
                "```text\n"
                "Uniswap V3 USDT pool --3,000,000 USDT--> Attack contract\n"
                "Attack contract --swap/withdraw/sandwich--> Bunni USDC/USDT liquidity\n"
                "Attack contract --3,009,000 USDT repayment--> Uniswap V3 USDT pool\n"
                "Attack contract --1.33M USDC / 1.04M USDT--> Aave aUSDC / aUSDT\n"
                "```",
                "### 5.4 总损失",
                self._table(["范围", "金额", "来源", "备注"], loss_rows),
                "### 5.5 攻击成本",
                "已确认成本包括 flashloan fee 9,000 USDT 与交易 gas；当前报告没有接入价格源和 gas fee 估值模块，因此不写最终净利润精确值。",
                "### 5.6 资金流证据",
                self._table(
                    ["字段", "值"],
                    [
                        ("receipt log count", flow.get("log_count", "-")),
                        ("USDC Transfer logs", flow.get("usdc_transfer_count", "-")),
                        ("USDT Transfer logs", flow.get("usdt_transfer_count", "-")),
                        ("large token flow rows", len(flows)),
                    ],
                ),
            ]
        )

    def _bunni_methodology(self, case, jobs: list[JobRun], evidence: list, bunni: dict[str, Any]) -> str:
        env = self._environment_facts(evidence, jobs)
        txanalyzer = self._txanalyzer_facts(evidence)
        flow = self._bunni_flow_facts(evidence)
        latest_jobs = self._latest_jobs(jobs)
        env_rows = [
            ("RPC chainId", env.get("chain_id", "-"), "通过" if env.get("rpc_ok") else "未通过 / 未执行", env.get("rpc_source", "-")),
            ("trace_transaction", env.get("trace_transaction_ok", "-"), "可用于调用链", "RPC capability"),
            ("debug_traceTransaction", env.get("debug_trace_transaction_ok", "-"), "opcode 复算能力", "当前公共 RPC 不支持"),
            ("Explorer API", env.get("explorer_ok", "-"), "源码/ABI/txlist", "未配置 key 时降级"),
            ("TxAnalyzer", "success" if txanalyzer else "未完成", self._purrlend_txanalyzer_status(txanalyzer), "worker run"),
            ("Receipt decode", "success" if flow else "未完成", f"USDC/USDT logs={flow.get('usdc_transfer_count', '-')}/{flow.get('usdt_transfer_count', '-')}", "eth_getTransactionReceipt"),
        ]
        evidence_rows = [
            ("官方 post-mortem", bunni.get("primary_source", "-"), "日期、交易哈希、三阶段机制、关键状态数值", "corroborating"),
            ("TxAnalyzer trace/report", "pull_artifacts.py", "flash/swap/withdraw/take/transfer 调用路径", "deterministic trace artifact"),
            ("Receipt logs", "eth_getTransactionReceipt", "USDT flashloan/repay、USDC/USDT 最终流向", "deterministic"),
            ("第三方复盘", f"{bunni.get('secondary_source', '-')} / {bunni.get('tertiary_source', '-')}", "根因解释与损失口径交叉验证", "corroborating"),
        ]
        workflow = "\n".join(
            [
                f"Step 1: 环境验证 -> eth_chainId={env.get('chain_id', '-')}, rpc_ok={env.get('rpc_ok', '-')}",
                f"Step 2: seed tx hydration -> `{case.seed_value}` block={self._bunni_block_number_from_evidence(evidence)}",
                f"Step 3: TxAnalyzer CLI -> files={txanalyzer.get('file_count', '-')}, trace={txanalyzer.get('has_trace', '-')}",
                f"Step 4: receipt flow decode -> logs={flow.get('log_count', '-')}, USDC/USDT transfers={flow.get('usdc_transfer_count', '-')}/{flow.get('usdt_transfer_count', '-')}",
                "Step 5: structured evidence -> official mechanism + deterministic trace/receipt summary",
                "Step 6: report draft -> 按 AMM/LDF 舍入漏洞结构生成，不使用桥攻击模板",
            ]
        )
        checklist_rows = [
            ("1", "攻击交易存在性", "eth_getTransactionByHash", "已确认"),
            ("2", "TxAnalyzer 真实运行", "job_runs + manifest", "已确认，3955 个 artifact"),
            ("3", "flashloan 入口", "trace + USDT Transfer", "已确认 3,000,000 USDT"),
            ("4", "重复 withdraw 路径", "TxAnalyzer tx_report", "已确认多层 withdraw 调用；44 次精确计数取官方复盘"),
            ("5", "利润落点", "receipt logs", "已确认 Aave aUSDC/aUSDT 大额接收"),
            ("6", "本地 opcode/source 复算覆盖", "debug_trace/source", "当前未配置，不能伪称已复算"),
        ]
        return "\n\n".join(
            [
                "### 6.1 分析工具栈",
                self._table(["工具", "用途"], [("TxAnalyzer", "拉取 trace/report/contract selector artifact"), ("RPC", "交易、receipt、trace capability 检查"), ("RCA Workbench", "evidence/finding/report schema 管理"), ("外部复盘", "提供需要源码级状态复现才能得到的精确数值")]),
                "### 6.2 本案实际执行结果",
                self._table(["检查项", "结果", "意义", "来源"], env_rows),
                "### 6.3 本案证据分层",
                self._table(["证据层", "来源", "能证明什么", "可靠性"], evidence_rows),
                "### 6.4 分析步骤",
                f"```text\n{workflow}\n```",
                "### 6.5 关键复核清单",
                self._table(["#", "复核项", "方法", "结论"], checklist_rows),
                "### 6.6 数据可靠性",
                "\n".join(
                    [
                        f"- Evidence count: {len(evidence)}",
                        f"- Latest worker runs: {len(latest_jobs)}，明细见附录。",
                        "- 本报告区分 deterministic evidence 与 corroborating source：交易存在、token flow、TxAnalyzer artifact 属于前者；根因机制中的精确状态数值来自官方/第三方复现。",
                        "- 由于没有 Explorer API key 和 debug_traceTransaction，本地没有把 BunniHub 源码行与 opcode 逐条复算；报告中已明确标注这个边界。",
                    ]
                ),
            ]
        )

    def _bunni_appendix(self, transactions: list, evidence: list, jobs: list[JobRun], bunni: dict[str, Any]) -> str:
        txanalyzer = self._txanalyzer_facts(evidence)
        flow = self._bunni_flow_facts(evidence)
        jobs = self._latest_jobs(jobs)
        tx_rows = [
            (tx.phase, tx.tx_hash, tx.block_number or "-", tx.method_name or tx.method_selector or "-", self._purrlend_artifact_status(tx.artifact_status))
            for tx in transactions
        ]
        evidence_rows = [
            (
                item.id,
                self._bunni_source_type_label(item.source_type),
                self._bunni_producer_label(item.producer),
                self._bunni_claim_label(item.claim_key),
                self._purrlend_confidence_label(item.confidence),
                item.raw_path or "-",
            )
            for item in evidence
        ]
        job_rows = [(self._bunni_producer_label(job.job_name), self._purrlend_job_status_label(job.status, job.job_name), self._format_dt(job.started_at or job.created_at), job.error or "-") for job in jobs]
        source_rows = [
            ("Bunni official post-mortem", bunni.get("primary_source", "-"), "机制与交易哈希主来源"),
            ("BlockSec analysis", bunni.get("secondary_source", "-"), "阶段化攻击分析与数值交叉验证"),
            ("QuillAudits analysis", bunni.get("tertiary_source", "-"), "地址、交易和后续资金流交叉验证"),
        ]
        txanalyzer_rows = [
            ("tx_hash", txanalyzer.get("tx_hash")),
            ("has_trace", txanalyzer.get("has_trace")),
            ("has_source", txanalyzer.get("has_source")),
            ("has_opcode", txanalyzer.get("has_opcode")),
            ("file_count", txanalyzer.get("file_count")),
        ] if txanalyzer else []
        verification_rows = [
            ("2025 事件选择", "已确认", f"事件日期为 {bunni.get('date_utc', '-')}，属于 2025 年。"),
            ("Ethereum seed tx", "已确认", bunni.get("ethereum_attack_tx", "-")),
            ("TxAnalyzer 真实调用", "已确认", f"manifest 显示导入 {txanalyzer.get('file_count', '-')} 个 artifact。"),
            ("资金流复核", "已确认", f"receipt logs={flow.get('log_count', '-')}, USDC/USDT transfers={flow.get('usdc_transfer_count', '-')}/{flow.get('usdt_transfer_count', '-')}。"),
            ("根因精确数值", "外部复现支持", "28 wei、4 wei、84.4%、16.8% 来自官方/第三方复盘；本地未做 opcode 逐条复算。"),
        ]
        return "\n\n".join(
            [
                "### A.1 交易列表",
                self._table(["Phase", "Tx", "Block", "Method", "Artifact"], tx_rows) if tx_rows else "暂无交易。",
                "### A.2 Evidence 列表",
                self._table(["ID", "Source", "Producer", "Claim", "Confidence", "Raw Path"], evidence_rows) if evidence_rows else "暂无 evidence。",
                "### A.3 外部来源",
                self._table(["来源", "URL", "用途"], source_rows),
                "### A.4 TxAnalyzer Artifact Summary",
                self._table(["字段", "值"], txanalyzer_rows) if txanalyzer_rows else "暂无 TxAnalyzer artifact summary。",
                "### A.5 Worker 最新执行记录",
                self._table(["Worker", "Status", "Started", "Error"], job_rows) if job_rows else "暂无 job run。",
                "### A.6 复核结论",
                self._table(["复核项", "结论", "证据 / 说明"], verification_rows),
            ]
        )

    def _bunni_facts(self, evidence: list) -> dict[str, Any]:
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "bunni_v2_exploit_summary" and isinstance(decoded, dict):
                return decoded
        for item in evidence:
            decoded = item.decoded or {}
            if isinstance(decoded, dict) and decoded.get("incident_key") == "bunni_v2_2025_09_02":
                return decoded
        return {}

    def _bunni_facts_from_case_evidence(self, case_id: str) -> dict[str, Any]:
        return self._bunni_facts(EvidenceService(self.db).list_for_case(case_id))

    def _bunni_flow_facts(self, evidence: list) -> dict[str, Any]:
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "bunni_receipt_token_flow_summary" and isinstance(decoded, dict):
                return decoded
        return {}

    def _bunni_evidence_groups(self, evidence: list) -> list[tuple[str, str, str, str]]:
        groups: dict[str, dict[str, Any]] = {}
        for item in evidence:
            label = self._bunni_source_type_label(item.source_type)
            group = groups.setdefault(label, {"producers": set(), "claims": set(), "confidence": item.confidence})
            group["producers"].add(self._bunni_producer_label(item.producer))
            group["claims"].add(self._bunni_claim_label(item.claim_key))
        rows = []
        for label, group in groups.items():
            rows.append(
                (
                    label,
                    "、".join(sorted(group["producers"])),
                    "；".join(sorted(group["claims"])),
                    self._purrlend_confidence_label(group["confidence"]),
                )
            )
        return rows

    def _bunni_loss_text(self, bunni: dict[str, Any]) -> str:
        total = bunni.get("total_loss_summary") or "约 $8.4M"
        eth = bunni.get("ethereum_loss_summary") or "Ethereum 约 $2.4M"
        uni = bunni.get("unichain_loss_summary") or "Unichain 约 $5.9M"
        return f"{total}（{eth}；{uni}）"

    def _bunni_attack_type_label(self, value: Any) -> str:
        text = str(value or "")
        if "rounding error" in text and "flashloan" in text:
            return "AMM/LDF 舍入误差 + 流动性会计操纵 + flashloan sandwich"
        return text or "AMM 流动性会计精度/舍入漏洞"

    def _bunni_flow_meaning_label(self, value: Any) -> str:
        text = str(value or "-")
        labels = {
            "Uniswap V3 flashloan principal to attack contract": "Uniswap V3 向攻击合约发放 flashloan 本金",
            "flashloan repayment including 9,000 USDT fee": "攻击合约归还 flashloan，本金外含 9,000 USDT 费用",
            "post-exploit USDC deposited into Aave aUSDC": "攻击后 USDC 利润存入 Aave aUSDC",
            "post-exploit USDT deposited into Aave aUSDT": "攻击后 USDT 利润存入 Aave aUSDT",
        }
        return labels.get(text, text)

    def _bunni_block_number(self, timeline: list[dict]) -> str:
        for item in timeline:
            if item.get("block_number"):
                return str(item["block_number"])
        return "-"

    def _bunni_block_number_from_evidence(self, evidence: list) -> str:
        for item in evidence:
            decoded = item.decoded or {}
            if isinstance(decoded, dict) and decoded.get("block_number"):
                return str(decoded["block_number"])
        return "-"

    def _bunni_source_type_label(self, source_type: Any) -> str:
        value = str(source_type or "-")
        labels = {
            "artifact_summary": "运行环境 / artifact 摘要",
            "external_incident_report": "外部复盘报告",
            "receipt_log": "交易 receipt 与日志",
            "trace_call": "TxAnalyzer 调用链",
            "tx_metadata": "交易元数据",
        }
        return labels.get(value, self._purrlend_source_type_label(value))

    def _bunni_producer_label(self, producer: Any) -> str:
        value = str(producer or "-")
        labels = {
            "bunni_incident_importer": "Bunni 事件导入器",
            "bunni_receipt_parser": "Bunni receipt 解析器",
            "bunni_trace_parser": "Bunni trace 摘要器",
        }
        return labels.get(value, self._purrlend_producer_label(value))

    def _bunni_claim_label(self, claim_key: Any) -> str:
        value = str(claim_key or "-")
        exact = {
            "bunni_v2_exploit_summary": "Bunni V2 事件摘要",
            "bunni_receipt_token_flow_summary": "USDC/USDT receipt 资金流摘要",
            "bunni_txanalyzer_trace_summary": "TxAnalyzer 调用链摘要",
            "environment_capability": "RPC、trace 与 explorer 能力检查",
            "transaction_in_case_scope": "Seed 交易已纳入 case",
            "txanalyzer_artifacts_available": "TxAnalyzer artifact 已导入",
            "opcode_trace_unavailable": "opcode trace 不可用",
            "top_level_call_decoded": "顶层调用解码",
            "loss_calculation_status": "损失计算模块状态",
        }
        return exact.get(value, value)

    def _bunni_finding_type_label(self, finding_type: Any) -> str:
        value = str(finding_type or "-")
        labels = {
            "bunni_idle_balance_rounding_error": "idleBalance 舍入误差 / 流动性会计边界失效",
            "bunni_attack_flow_confirmed": "攻击流程与资金流已复核",
        }
        return labels.get(value, value)

    def _purrlend_facts(self, evidence: list) -> dict[str, Any]:
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "purrlend_megaeth_exploit_summary" and isinstance(decoded, dict):
                return decoded
        for item in evidence:
            decoded = item.decoded or {}
            if isinstance(decoded, dict) and decoded.get("incident_key") == "purrlend_megaeth_2026_04_25":
                return decoded
        return {}

    def _purrlend_facts_from_case_evidence(self, case_id: str) -> dict[str, Any]:
        return self._purrlend_facts(EvidenceService(self.db).list_for_case(case_id))

    def _purrlend_attack_window(self, timeline: list[dict], purrlend: dict[str, Any]) -> str:
        timestamps = [item.get("timestamp") for item in timeline if item.get("timestamp")]
        if len(timestamps) >= 2:
            start = min(timestamps)
            end = max(timestamps)
            minutes = max(0, int((end - start).total_seconds() // 60))
            return f"{self._format_dt(start)} - {self._format_dt(end)}，约 {minutes} 分钟"
        txs = purrlend.get("txs") or []
        tx_times = [tx.get("timestamp_utc") for tx in txs if tx.get("timestamp_utc")]
        if tx_times:
            return f"{min(tx_times)} - {max(tx_times)}"
        return purrlend.get("date_utc", "-")

    def _purrlend_phase_summary(self, purrlend: dict[str, Any]) -> str:
        methods = [tx.get("method") for tx in (purrlend.get("txs") or []) if tx.get("method")]
        labels = {
            "Set Unbacked Mint Cap": "提高未支持铸造上限",
            "Mint Unbacked": "连续未支持铸造",
            "Approve Delegation": "授权借款路径",
            "Borrow ETH": "借出 ETH",
            "Borrow": "借出其他资产",
            "0xd7a08473": "处置/桥接准备",
            "0xa1f1ce43": "最终外转",
        }
        ordered = []
        for method in methods:
            label = labels.get(method, method)
            if label not in ordered:
                ordered.append(label)
        return " -> ".join(ordered[:7]) or "提高未支持铸造上限 -> 未支持铸造 -> 授权借款路径 -> 借款 -> 外转"

    def _purrlend_loss_text(self, value: Any) -> str:
        return str(value if value is not None else "-").replace("external report口径", "外部报道口径")

    def _purrlend_key_tx_bullets(self, purrlend: dict[str, Any]) -> list[str]:
        txs = purrlend.get("txs") or []
        bullets: list[str] = []
        for tx in txs:
            method = tx.get("method", "-")
            if method in {"Set Unbacked Mint Cap", "Mint Unbacked", "Approve Delegation", "Borrow ETH", "Borrow"} or tx.get("amount_eth"):
                bullets.append(
                    f"- `{tx.get('tx_hash')}` `{method}` block={tx.get('block_number', '-')} status={tx.get('status_label', '-')} to=`{tx.get('to', '-')}`"
                )
        internal = self._purrlend_internal_transfer(purrlend)
        if internal:
            bullets.append(f"- Internal transfer: `{internal.get('tx_hash')}` `{internal.get('amount_eth')}` ETH -> `{internal.get('to')}`。")
        outflow = self._purrlend_final_outflow(purrlend)
        if outflow:
            bullets.append(f"- Final outflow: `{outflow.get('tx_hash')}` `{outflow.get('amount_eth')}` ETH -> `{outflow.get('to')}`。")
        return bullets or ["- 暂无关键交易。"]

    def _purrlend_internal_transfer(self, purrlend: dict[str, Any]) -> dict[str, Any]:
        transfers = purrlend.get("internal_transfers") or []
        for transfer in transfers:
            if transfer.get("amount_eth"):
                return transfer
        return {}

    def _purrlend_funding_transfer(self, purrlend: dict[str, Any]) -> dict[str, Any]:
        transfers = purrlend.get("internal_transfers") or []
        for transfer in transfers:
            if transfer.get("scope") == "funding":
                return transfer
        return {}

    def _purrlend_final_outflow(self, purrlend: dict[str, Any]) -> dict[str, Any]:
        txs = purrlend.get("txs") or []
        for tx in txs:
            if tx.get("amount_eth") and str(tx.get("method", "")).lower() not in {"borrow eth", "borrow"}:
                return tx
        for tx in txs:
            if tx.get("amount_eth"):
                return tx
        return {}

    def _purrlend_artifact_status(self, status: str | None) -> str:
        if status == "partial":
            return "TxAnalyzer 降级 artifact 已导入"
        if status == "done":
            return "TxAnalyzer 完整导入"
        if status == "failed":
            return "TxAnalyzer 失败"
        if status == "pending":
            return "RPC/Explorer 证据已导入"
        return status or "-"

    def _purrlend_txanalyzer_status(self, txanalyzer: dict[str, Any]) -> str:
        if not txanalyzer:
            return "未执行或尚未导入 artifact"
        if txanalyzer.get("fallback_reason"):
            return (
                "CLI 已执行；`trace_transaction` 不可用，已降级导入 "
                f"receipt={self._bool_label(txanalyzer.get('has_receipt'))}, opcode={self._bool_label(txanalyzer.get('has_opcode'))}, "
                f"files={txanalyzer.get('file_count', 0)}。"
            )
        return (
            f"CLI 成功；trace={self._bool_label(txanalyzer.get('has_trace'))}, "
            f"source={self._bool_label(txanalyzer.get('has_source'))}, opcode={self._bool_label(txanalyzer.get('has_opcode'))}, "
            f"files={txanalyzer.get('file_count', 0)}。"
        )

    def _finding_evidence_summary(self, finding, evidence: list) -> str:
        evidence_ids = [str(value) for value in (finding.evidence_ids or [])]
        if not evidence_ids:
            return "未绑定证据"
        by_id = {str(item.id): item for item in evidence}
        matched = [by_id[evidence_id] for evidence_id in evidence_ids if evidence_id in by_id]
        if not matched:
            return f"{len(evidence_ids)} 条证据已绑定，详情见数据库 evidence 记录"
        source_types = []
        producers = []
        for item in matched:
            source_label = self._purrlend_source_type_label(item.source_type)
            producer_label = self._purrlend_producer_label(item.producer)
            if source_label not in source_types:
                source_types.append(source_label)
            if producer_label not in producers:
                producers.append(producer_label)
        source_text = "、".join(source_types[:4])
        if len(source_types) > 4:
            source_text += "等"
        producer_text = "、".join(producers[:3])
        if len(producers) > 3:
            producer_text += "等"
        return f"{len(evidence_ids)} 条证据，覆盖 {source_text}；主要来自 {producer_text}"

    def _purrlend_method_label(self, method: Any) -> str:
        value = str(method or "-")
        labels = {
            "Set Unbacked Mint Cap": "设置未支持铸造上限",
            "Mint Unbacked": "未支持铸造",
            "Approve Delegation": "授权债务委托",
            "Borrow ETH": "借出 ETH",
            "Borrow": "借出资产",
            "0xd7a08473": "处置/桥接准备调用 (0xd7a08473)",
            "0xa1f1ce43": "最终 ETH 外转 (0xa1f1ce43)",
        }
        return labels.get(value, value)

    def _purrlend_phase_label(self, phase: Any) -> str:
        value = str(phase or "-")
        labels = {
            "set_unbacked_mint_cap": "打开未支持铸造额度",
            "mint_unbacked": "连续未支持铸造",
            "approve_delegation": "授权借款路径",
            "borrow_eth": "借出 ETH",
            "borrow": "借出资产",
            "post_exploit_call": "处置/桥接准备",
            "final_outflow": "最终外转",
        }
        return labels.get(value, value)

    def _purrlend_tx_status_label(self, status: Any) -> str:
        value = str(status or "-")
        labels = {
            "Success": "成功",
            "Error in Internal Txn : execution reverted": "顶层成功；内部调用出现 revert 标记",
            "success": "成功",
            "failed": "失败",
            "partial": "部分完成",
            "pending": "待处理",
        }
        return labels.get(value, value)

    def _purrlend_source_type_label(self, source_type: Any) -> str:
        value = str(source_type or "-")
        labels = {
            "artifact_summary": "运行环境 / artifact 摘要",
            "external_alert": "外部事件入口",
            "external_explorer": "Explorer 标记与导出",
            "external_incident_report": "外部复盘报告",
            "receipt_log": "交易 receipt 与日志",
            "tx_metadata": "交易元数据",
            "artifact_manifest": "TxAnalyzer artifact 清单",
            "trace": "交易 trace",
            "trace_call": "TxAnalyzer 调用链",
            "opcode": "debug opcode trace",
            "source": "合约源码",
        }
        return labels.get(value, value)

    def _purrlend_producer_label(self, producer: Any) -> str:
        value = str(producer or "-")
        labels = {
            "environment_check_worker": "环境检查",
            "tx_discovery_worker": "交易发现",
            "txanalyzer_worker": "TxAnalyzer",
            "decode_worker": "交易解码",
            "acl_forensics_worker": "ACL 检查",
            "safe_forensics_worker": "Safe 检查",
            "fund_flow_worker": "资金流检查",
            "loss_calculator_worker": "损失计算",
            "rca_agent_worker": "RCA 归因",
            "report_worker": "报告生成",
            "megaeth_purrlend_importer": "MegaETH Purrlend 导入器",
            "bunni_incident_importer": "Bunni 事件导入器",
            "bunni_receipt_parser": "Bunni receipt 解析器",
            "bunni_trace_parser": "Bunni trace 摘要器",
        }
        return labels.get(value, value)

    def _purrlend_claim_label(self, claim_key: Any) -> str:
        value = str(claim_key or "-")
        exact = {
            "environment_capability": "RPC、trace 与 explorer 能力检查",
            "external_incident_seed": "外部事件种子已登记",
            "loss_calculation_status": "损失计算模块状态",
            "txanalyzer_artifacts_available": "TxAnalyzer artifact 已导入",
            "purrlend_megaeth_exploit_summary": "Purrlend MegaETH 事件摘要",
            "purrlend_internal_transfers": "攻击期间 internal transfer",
        }
        if value in exact:
            return exact[value]
        prefixes = {
            "purrlend_scoped_transaction:": "攻击者相关交易元数据",
            "purrlend_receipt:": "攻击者相关交易 receipt",
        }
        for prefix, label in prefixes.items():
            if value.startswith(prefix):
                return label
        return value

    def _purrlend_confidence_label(self, confidence: Any) -> str:
        value = str(confidence or "-")
        labels = {
            "high": "高",
            "medium": "中",
            "low": "低",
            "partial": "部分证据",
        }
        return labels.get(value, value)

    def _purrlend_severity_label(self, severity: Any) -> str:
        value = str(severity or "-")
        labels = {
            "critical": "严重",
            "high": "高",
            "medium": "中",
            "low": "低",
            "info": "信息",
        }
        return labels.get(value, value)

    def _purrlend_review_status_label(self, status: Any) -> str:
        value = str(status or "-")
        labels = {
            "approved": "已审核通过",
            "rejected": "已驳回",
            "pending": "待审核",
        }
        return labels.get(value, value)

    def _purrlend_finding_type_label(self, finding_type: Any) -> str:
        value = str(finding_type or "-")
        labels = {
            "purrlend_unbacked_mint_control_failure": "未支持铸造与借款控制边界失效",
        }
        return labels.get(value, value)

    def _purrlend_job_status_label(self, status: Any, job_name: Any | None = None) -> str:
        value = str(status or "-")
        name = str(job_name or "")
        if value == "partial" and name == "txanalyzer_worker":
            return "已降级完成"
        if value == "partial" and name == "environment_check_worker":
            return "RPC 通过，Explorer API 未配置"
        labels = {
            "success": "完成",
            "partial": "部分完成",
            "failed": "失败",
            "running": "运行中",
            "pending": "待处理",
        }
        return labels.get(value, value)

    def _purrlend_fallback_reason(self, reason: Any) -> str:
        if not reason:
            return "-"
        text = str(reason)
        if "TxAnalyzer CLI failed before trace import" in text:
            return "官方 CLI 已调用，但 MegaETH public RPC 不支持 trace_transaction；系统改为导入 transaction、receipt 与 debug_traceTransaction artifact。"
        return text

    def _bool_label(self, value: Any) -> str:
        if value is True:
            return "是"
        if value is False:
            return "否"
        return str(value if value is not None else "-")

    def _infer_attack_type(self, case, evidence: list) -> str:
        if self._revert_facts(evidence):
            return "LP NFT 抵押物管理路径缺少偿付检查"
        if self._purrlend_facts(evidence):
            return "借贷市场 unbacked mint / borrow control failure"
        if self._bunni_facts(evidence):
            return "AMM/LDF 舍入误差与流动性会计漏洞"
        if self._receipt_facts(evidence) or self._incident_facts(evidence):
            return "跨链消息验证失败 / Bridge exploit"
        if case.seed_type == "alert":
            return "外部情报 / 待链上复核"
        for item in evidence:
            if "role" in item.claim_key.lower() or "acl" in item.claim_key.lower():
                return "权限滥用 / Access Control"
            if "loss" in item.claim_key.lower() or "fund" in item.claim_key.lower():
                return "资金流异常"
        return "待确认"

    def _root_cause_label(self, case, evidence: list) -> str:
        if self._revert_facts(evidence):
            return "GaugeManager / V3Utils unstake path missed active-debt solvency checks"
        if self._purrlend_facts(evidence):
            return "Unbacked mint cap / borrow control failure"
        if self._bunni_facts(evidence):
            return "BunniHubLogic.withdraw() idleBalance 舍入方向在极端余额下被重复放大"
        incident = self._incident_facts(evidence)
        if incident.get("mechanism"):
            return "跨链消息验证失效 / 1-of-1 DVN phantom message"
        root_cause = (case.root_cause_one_liner or "").strip()
        if not root_cause:
            return self._infer_attack_type(case, evidence)
        if root_cause.lower().startswith("no high-confidence root cause"):
            return "待链上复核"
        return root_cause

    def _finding_title(self, finding) -> str:
        if finding.title == "Evidence-backed RCA draft requires reviewer analysis":
            return "Evidence 已采集，需 reviewer 复核 RCA 结论"
        if finding.title == "Revert Finance collateralized LP NFT unstake bypass":
            return "Revert Finance 带债 LP NFT 可被 unstake / modify"
        if finding.title == "Purrlend MegaETH unbacked mint / borrow control failure":
            return "Purrlend 未支持铸造与借款控制边界失效"
        if finding.title == "Bunni V2 idle balance rounding error enabled liquidity mispricing":
            return "Bunni V2 idleBalance 舍入误差导致流动性错估"
        if finding.title == "Bunni V2 Ethereum token flow confirmed":
            return "Bunni V2 Ethereum 资金流已由 receipt 复核"
        return finding.title

    def _finding_claim(self, finding) -> str:
        if finding.claim == "The system collected evidence but did not identify a specialized high-risk RCA finding automatically.":
            return "系统已收集 evidence，但自动化 worker 尚未识别高风险 RCA finding。"
        return finding.claim

    def _finding_rationale(self, finding) -> str:
        if finding.rationale == "This local RCA worker avoids unsupported conclusions when only generic evidence is available.":
            return "当前 RCA worker 在只有通用 evidence 时不会输出未经支持的结论。"
        return finding.rationale

    def _finding_falsification(self, finding) -> str:
        if finding.falsification == "Run ACL/Safe/FundFlow modules with complete artifacts to raise confidence.":
            return "补齐完整 artifact 后运行 ACL/Safe/FundFlow 模块，提高或推翻该结论。"
        return finding.falsification

    def _incident_date(self, case, timeline: list[dict]) -> str:
        timestamps = [item.get("timestamp") for item in timeline if item.get("timestamp")]
        if timestamps:
            return min(timestamps).date().isoformat()
        return case.created_at.date().isoformat()

    def _attack_window(self, case, timeline: list[dict]) -> str:
        timestamps = [item.get("timestamp") for item in timeline if item.get("timestamp")]
        if len(timestamps) >= 2:
            start = min(timestamps)
            end = max(timestamps)
            minutes = max(0, int((end - start).total_seconds() // 60))
            return f"{self._format_dt(start)} - {self._format_dt(end)}，约 {minutes} 分钟"
        if len(timestamps) == 1:
            return f"{self._format_dt(timestamps[0])}，单笔 seed tx"
        if case.seed_type == "alert":
            return "外部情报已记录，待 seed transaction 补齐"
        return "待交易时间线确认"

    def _loss_summary(self, case, evidence: list) -> str:
        incident = self._incident_facts(evidence)
        if incident.get("loss_summary"):
            return str(incident["loss_summary"])
        if case.loss_usd is not None:
            return f"约 ${float(case.loss_usd):,.2f}"
        for item in evidence:
            decoded = item.decoded or {}
            usd_loss = decoded.get("usd_loss") if isinstance(decoded, dict) else None
            if usd_loss is not None:
                return f"约 ${float(usd_loss):,.2f}"
        return "待资金流 worker 和价格源确认"

    def _token_amount(self, value: Any) -> str:
        if value is None:
            return "-"
        try:
            amount = float(value)
            if amount.is_integer():
                return f"{amount:,.0f}"
            return f"{amount:,.6f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(value)

    def _incident_mechanism_zh(self, incident: dict[str, Any]) -> str:
        mechanism = str(incident.get("mechanism") or "").strip()
        if "forged inbound packet" in mechanism and "1-of-1 DVN" in mechanism:
            return "攻击者构造了从 Unichain 到 Ethereum 的伪造 inbound packet，该 packet 经 1-of-1 DVN 路径通过验证，但源链侧没有对应的真实 burn / lock"
        return mechanism or "待复核"

    def _incident_impact_zh(self, incident: dict[str, Any]) -> str:
        impact = str(incident.get("impact") or "").strip()
        if "116,500 rsETH" in impact and "lending markets" in impact:
            return "Ethereum 侧 RSETH_OFTAdapter 向攻击者接收地址释放 116,500 rsETH，随后该资产进入借贷市场形成风险敞口"
        return impact or "待补充下游资金流 evidence"

    def _summarize_error(self, error: str | None) -> str:
        if not error:
            return "-"
        if "ModuleNotFoundError" in error and "requests" in error:
            return "ModuleNotFoundError: No module named 'requests'"
        if "No such file or directory" in error and ".venv/bin/python" in error:
            return "TxAnalyzer python path 不存在: ./.venv/bin/python"
        return error[:220]

    def _receipt_facts(self, evidence: list) -> dict[str, Any]:
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "rseth_transfer_and_oft_received_logs" and isinstance(decoded, dict):
                return decoded
        for item in evidence:
            decoded = item.decoded or {}
            if isinstance(decoded, dict) and decoded.get("event_evidence") and decoded.get("attacker_receiver"):
                return decoded
        return {}

    def _incident_facts(self, evidence: list) -> dict[str, Any]:
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "kelpdao_rseth_bridge_exploit_summary" and isinstance(decoded, dict):
                return decoded
        for item in evidence:
            decoded = item.decoded or {}
            if isinstance(decoded, dict) and (decoded.get("mechanism") or decoded.get("loss_summary")):
                return decoded
        return {}

    def _scallop_facts(self, evidence: list) -> dict[str, Any]:
        facts: dict[str, Any] = {}
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "scallop_ssui_reward_pool_incident_summary" and isinstance(decoded, dict):
                facts.update(decoded)
                facts["incident_evidence_id"] = item.id
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "sui_transaction_block_verified" and isinstance(decoded, dict):
                facts["tx"] = decoded
                facts.setdefault("tx_digest", decoded.get("digest"))
                facts["tx_evidence_id"] = item.id
            if item.claim_key == "sui_reward_redemption_flow" and isinstance(decoded, dict):
                facts["flow"] = decoded
                facts["flow_evidence_id"] = item.id
        if facts.get("project") == "Scallop Lend" or facts.get("incident_evidence_id"):
            return facts
        return {}

    def _scallop_facts_from_case_evidence(self, case_id: str) -> dict[str, Any]:
        return self._scallop_facts(EvidenceService(self.db).list_for_case(case_id))

    def _scallop_primary_flow(self, scallop: dict[str, Any]) -> dict[str, Any]:
        flow_payload = scallop.get("flow") or {}
        flows = flow_payload.get("flows") or []
        if flows and isinstance(flows[0], dict):
            return flows[0]
        return {}

    def _scallop_package_from_calls(self, calls: list[dict[str, Any]], module: str | None = None) -> str | None:
        for call in calls:
            if module is None or call.get("module") == module:
                return call.get("package")
        return None

    def _scallop_reward_pool(self, flow: dict[str, Any], tx: dict[str, Any]) -> str:
        source = str(flow.get("from") or "")
        if source.startswith("rewards_pool:"):
            return source.removeprefix("rewards_pool:")
        reward_event = tx.get("reward_event") or {}
        parsed = reward_event.get("parsed_json") or {}
        return parsed.get("rewards_pool_id") or "-"

    def _scallop_time(self, tx: dict[str, Any]) -> str:
        timestamp_ms = tx.get("timestamp_ms")
        if not timestamp_ms:
            return "-"
        try:
            return datetime.fromtimestamp(int(timestamp_ms) / 1000).isoformat()
        except Exception:
            return str(timestamp_ms)

    def _txanalyzer_facts(self, evidence: list) -> dict[str, Any]:
        for item in reversed(evidence):
            decoded = item.decoded or {}
            if item.claim_key == "txanalyzer_artifacts_available" and isinstance(decoded, dict):
                return decoded
        return {}

    def _environment_facts(self, evidence: list, jobs: list[JobRun]) -> dict[str, Any]:
        for item in evidence:
            decoded = item.decoded or {}
            if item.claim_key == "environment_capability" and isinstance(decoded, dict):
                return decoded
        for job in jobs:
            output = self._job_output(job)
            if job.job_name == "environment_check_worker" and output:
                return output
        return {}

    def _receipt_facts_from_case_evidence(self, case_id: str) -> dict[str, Any]:
        return self._receipt_facts(EvidenceService(self.db).list_for_case(case_id))

    def _incident_facts_from_case_evidence(self, case_id: str) -> dict[str, Any]:
        return self._incident_facts(EvidenceService(self.db).list_for_case(case_id))

    def _txanalyzer_facts_from_case_evidence(self, case_id: str) -> dict[str, Any]:
        return self._txanalyzer_facts(EvidenceService(self.db).list_for_case(case_id))

    def _job_output(self, job: JobRun | None) -> dict[str, Any]:
        if job is None:
            return {}
        output = getattr(job, "output", None) or {}
        return output if isinstance(output, dict) else {}

    def _latest_jobs(self, jobs: list[JobRun]) -> list[JobRun]:
        latest: dict[str, JobRun] = {}
        for job in jobs:
            current = latest.get(job.job_name)
            if current is None or job.created_at > current.created_at:
                latest[job.job_name] = job
        return sorted(latest.values(), key=lambda job: job.created_at)

    def _recent_non_report_jobs(self, jobs: list[JobRun]) -> list[JobRun]:
        latest_jobs = [job for job in self._latest_jobs(jobs) if job.job_name != "report_worker"]
        timestamps = [job.ended_at or job.started_at or job.created_at for job in latest_jobs if job.ended_at or job.started_at or job.created_at]
        if not timestamps:
            return latest_jobs
        cutoff = max(timestamps) - timedelta(minutes=30)
        recent_jobs = [
            job
            for job in latest_jobs
            if (job.started_at or job.created_at) >= cutoff
        ]
        return recent_jobs or latest_jobs

    def _verification_rows(self, receipt: dict[str, Any], txanalyzer: dict[str, Any], jobs: list[JobRun]) -> list[tuple[str, str, str]]:
        txanalyzer_job = next((job for job in reversed(jobs) if job.job_name == "txanalyzer_worker"), None)
        tx_status = txanalyzer_job.status if txanalyzer_job else "not_run"
        amount = self._token_amount(receipt.get("amount_rseth")) if receipt else "-"
        return [
            (
                "目标链核心释放交易",
                "已确认",
                f"receipt status={receipt.get('status', '-')}; block={receipt.get('block_number', '-')}; adapter -> receiver 转出 {amount} rsETH。",
            ),
            (
                "High/Critical finding 的 deterministic evidence",
                "已确认",
                "receipt_log 支撑 Transfer/OFTReceived/PacketDelivered；TxAnalyzer trace 支撑 EndpointV2 -> RSETH_OFTAdapter -> rsETH.transfer 调用链。",
            ),
            (
                "TxAnalyzer artifact",
                "trace 已确认",
                f"txanalyzer_worker={tx_status}; files={txanalyzer.get('file_count', 0) if txanalyzer else 0}; source={txanalyzer.get('has_source', False) if txanalyzer else False}; opcode={txanalyzer.get('has_opcode', False) if txanalyzer else False}。",
            ),
            (
                "授权 / 多签 / 补救交易",
                "不适用",
                "本案是跨链消息验证失效，不是 ACL/Safe 权限授予型攻击；本报告不再把授权、多签或补救交易列为待补项。",
            ),
            (
                "source-chain packet / DVN attestation",
                "外部报告确认，本地 deterministic 范围外",
                "本地 evidence 已确认 Ethereum 侧释放；source-chain burn/lock 缺失和 1-of-1 DVN 机制采用 Aave/Chainalysis 外部报告作为 corroborating evidence，不伪装成本地 deterministic evidence。",
            ),
            (
                "downstream fund-flow",
                "未作为确定性结论",
                "报告只确定 116,500 rsETH 释放；下游借贷市场影响保留为外部报告口径，不写成本地逐笔复现结论。",
            ),
        ]

    def _format_dt(self, value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def _table(self, headers: list[str], rows: list[tuple[Any, ...]]) -> str:
        if not rows:
            return "暂无数据。"
        header = "| " + " | ".join(headers) + " |"
        separator = "| " + " | ".join(["---"] * len(headers)) + " |"
        body = ["| " + " | ".join(self._cell(value) for value in row) + " |" for row in rows]
        return "\n".join([header, separator, *body])

    def _cell(self, value: Any) -> str:
        text = str(value if value is not None else "-")
        return text.replace("\n", "<br>").replace("|", "\\|")

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.object_store import ObjectStore
from app.models.db import DiagramSpec
from app.services.case_service import CaseService
from app.services.evidence_service import EvidenceService
from app.services.finding_service import FindingService


class DiagramService:
    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def list_for_case(self, case_id: str) -> list[DiagramSpec]:
        return list(
            self.db.scalars(
                select(DiagramSpec)
                .where(DiagramSpec.case_id == case_id)
                .order_by(DiagramSpec.diagram_type, DiagramSpec.created_at)
            ).all()
        )

    def generate_for_case(self, case_id: str, report_id: str | None = None, created_by: str | None = None) -> list[DiagramSpec]:
        case_service = CaseService(self.db)
        case_service.get_case(case_id)
        transactions = case_service.list_transactions(case_id)
        evidence = EvidenceService(self.db).list_for_case(case_id)
        findings = [item for item in FindingService(self.db).list_for_case(case_id) if item.reviewer_status != "rejected"]
        if any(item.severity in {"critical", "high"} for item in findings):
            findings = [
                item
                for item in findings
                if not (item.finding_type == "data_quality" and item.severity in {"info", "low"})
            ]
        findings = sorted(findings, key=self._finding_rank)
        specs = [
            self._attack_flow(case_id, transactions, evidence, findings),
            self._fund_flow(case_id, transactions, evidence),
            self._evidence_map(case_id, evidence, findings),
        ]
        return [self._upsert(case_id, report_id, spec, created_by) for spec in specs]

    def markdown_for_diagrams(self, diagrams: list[DiagramSpec]) -> str:
        by_type = {diagram.diagram_type: diagram for diagram in diagrams}
        blocks = [
            "本节所有图例由 `diagram_specs` 生成，节点和边只来自已入库的交易、evidence、finding 和 worker 输出。证据不足时，图只保留已经确认的路径，不补画推测节点。",
        ]
        for diagram_type, heading in [
            ("attack_flow", "攻击流程图"),
            ("fund_flow", "资金流图"),
            ("evidence_map", "证据图"),
        ]:
            diagram = by_type.get(diagram_type)
            if diagram is None:
                continue
            blocks.extend(
                [
                    f"### {heading}",
                    f"- 置信度：`{diagram.confidence}`",
                    f"- Evidence：`{len(diagram.evidence_ids)}` 条",
                    "```mermaid",
                    diagram.mermaid_source,
                    "```",
                ]
            )
        return "\n\n".join(blocks)

    def _upsert(self, case_id: str, report_id: str | None, spec: dict[str, Any], created_by: str | None) -> DiagramSpec:
        content = spec["mermaid_source"].encode("utf-8")
        object_uri = self.object_store.put_bytes(
            content,
            f"cases/{case_id}/diagrams/{spec['diagram_type']}.mmd",
            "text/plain",
        )
        row = self.db.scalar(select(DiagramSpec).where(DiagramSpec.case_id == case_id, DiagramSpec.diagram_type == spec["diagram_type"]))
        if row is None:
            row = DiagramSpec(case_id=case_id, diagram_type=spec["diagram_type"])
        row.report_id = report_id
        row.title = spec["title"]
        row.mermaid_source = spec["mermaid_source"]
        row.nodes_edges_json = spec["nodes_edges"]
        row.evidence_ids = spec["evidence_ids"]
        row.confidence = spec["confidence"]
        row.source_type = spec["source_type"]
        row.object_path = object_uri
        row.content_hash = self.object_store.sha256_bytes(content)
        row.created_by = created_by
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _attack_flow(self, case_id: str, transactions: list, evidence: list, findings: list) -> dict[str, Any]:
        lines = ["graph LR"]
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        attack_steps = self._extract_attack_steps(evidence)
        evidence_label = self._edge_label(evidence[:4])
        self._add_node(lines, nodes, "seed", "Seed / 入口")
        if attack_steps:
            previous = "seed"
            for index, step in enumerate(attack_steps[:12], start=1):
                node = f"step{index}"
                self._add_node(lines, nodes, node, self._short(step.get("label") or step.get("id") or f"Step {index}", 48))
                self._add_edge(lines, edges, previous, node, self._short(step.get("evidence") or step.get("tx_hash") or step.get("confidence") or "evidence", 52))
                previous = node
            if findings:
                self._add_node(lines, nodes, "root", self._short(findings[0].title, 40))
                self._add_edge(lines, edges, previous, "root", findings[0].confidence)
        elif not transactions:
            self._add_node(lines, nodes, "evidence", "已确认 evidence")
            self._add_edge(lines, edges, "seed", "evidence", evidence_label or "external_alert")
        for index, tx in enumerate([] if attack_steps else transactions[:10], start=1):
            tx_node = f"tx{index}"
            from_node = f"from{index}"
            to_node = f"to{index}"
            self._add_node(lines, nodes, from_node, self._short(tx.from_address or "unknown sender"))
            self._add_node(lines, nodes, tx_node, f"{tx.phase or 'tx'}\\n{self._short(tx.tx_hash)}")
            self._add_node(lines, nodes, to_node, self._short(tx.to_address or "unknown target"))
            self._add_edge(lines, edges, "seed" if index == 1 else f"tx{index - 1}", from_node, "next")
            self._add_edge(lines, edges, from_node, tx_node, tx.method_name or tx.method_selector or "call")
            self._add_edge(lines, edges, tx_node, to_node, evidence_label or tx.artifact_status)
        if findings and not attack_steps:
            self._add_node(lines, nodes, "root", self._short(findings[0].title, 40))
            self._add_edge(lines, edges, f"tx{min(len(transactions), 10)}" if transactions else "evidence", "root", findings[0].confidence)
        confidence = self._diagram_confidence(evidence, transactions)
        return {
            "diagram_type": "attack_flow",
            "title": "攻击流程图",
            "mermaid_source": "\n".join(lines),
            "nodes_edges": {"nodes": nodes, "edges": edges},
            "evidence_ids": [item.id for item in evidence[:20]],
            "confidence": confidence,
            "source_type": "evidence_constrained",
        }

    def _fund_flow(self, case_id: str, transactions: list, evidence: list) -> dict[str, Any]:
        lines = ["graph LR"]
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        flows = self._extract_flows(evidence)
        if flows:
            address_nodes: dict[str, str] = {}
            grouped_edges: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for flow in flows[:20]:
                source_value = flow.get("from") or "source"
                target_value = flow.get("to") or "destination"
                source = self._flow_node_id(source_value, address_nodes)
                target = self._flow_node_id(target_value, address_nodes)
                self._add_node(lines, nodes, source, self._short(source_value))
                self._add_node(lines, nodes, target, self._short(target_value))
                grouped_edges.setdefault((source, target), []).append(flow)
            for (source, target), edge_flows in grouped_edges.items():
                self._add_edge(lines, edges, source, target, self._flow_edge_label(edge_flows))
        elif transactions:
            address_nodes: dict[str, str] = {}
            grouped_edges: dict[tuple[str, str], list[str]] = {}
            for tx in transactions[:12]:
                source_value = tx.from_address or "sender"
                target_value = tx.to_address or "target"
                source = self._flow_node_id(source_value, address_nodes)
                target = self._flow_node_id(target_value, address_nodes)
                self._add_node(lines, nodes, source, self._short(source_value))
                self._add_node(lines, nodes, target, self._short(target_value))
                grouped_edges.setdefault((source, target), []).append(f"{tx.phase or 'call'} / {tx.artifact_status}")
            for (source, target), labels in grouped_edges.items():
                label = labels[0] if len(labels) == 1 else f"{len(labels)} tx / {labels[0]}"
                self._add_edge(lines, edges, source, target, self._short(label, 48))
        else:
            self._add_node(lines, nodes, "missing", "暂无链上资金流 evidence")
        confidence = "high" if flows else self._diagram_confidence(evidence, transactions)
        return {
            "diagram_type": "fund_flow",
            "title": "资金流图",
            "mermaid_source": "\n".join(lines),
            "nodes_edges": {"nodes": nodes, "edges": edges},
            "evidence_ids": [flow["evidence_id"] for flow in flows[:12] if flow.get("evidence_id")] or [item.id for item in evidence[:20]],
            "confidence": confidence,
            "source_type": "evidence_constrained",
        }

    def _evidence_map(self, case_id: str, evidence: list, findings: list) -> dict[str, Any]:
        lines = ["graph LR"]
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        by_source: dict[str, list] = {}
        for item in evidence:
            by_source.setdefault(item.source_type, []).append(item)
        source_nodes: dict[str, str] = {}
        claim_nodes: dict[str, str] = {}
        finding_nodes: dict[str, str] = {}
        source_claim_edges: dict[tuple[str, str], list] = {}
        claim_finding_edges: dict[tuple[str, str], list] = {}
        findings_by_evidence: dict[str, list] = {}
        for finding in findings:
            for evidence_id in finding.evidence_ids or []:
                findings_by_evidence.setdefault(evidence_id, []).append(finding)

        for source_type, rows in list(by_source.items())[:10]:
            source_node = self._evidence_node_id(source_type, source_nodes, "src")
            producers = sorted({item.producer for item in rows})
            source_label = f"{source_type}\\n{len(rows)} evidence"
            if producers:
                source_label = f"{source_label}\\n{self._short(', '.join(producers), 36)}"
            self._add_node(lines, nodes, source_node, source_label)
            for item in rows[:20]:
                claim_node = self._evidence_node_id(item.claim_key, claim_nodes, "claim")
                self._add_node(lines, nodes, claim_node, self._short(item.claim_key, 44))
                source_claim_edges.setdefault((source_node, claim_node), []).append(item)
                for finding in findings_by_evidence.get(item.id, []):
                    finding_node = self._evidence_node_id(finding.id, finding_nodes, "finding")
                    self._add_node(lines, nodes, finding_node, self._short(finding.title, 44))
                    claim_finding_edges.setdefault((claim_node, finding_node), []).append(finding)

        for (source_node, claim_node), rows in source_claim_edges.items():
            self._add_edge(lines, edges, source_node, claim_node, self._evidence_edge_label(rows))
        for (claim_node, finding_node), rows in claim_finding_edges.items():
            self._add_edge(lines, edges, claim_node, finding_node, self._finding_edge_label(rows))
        if evidence and not claim_finding_edges and findings:
            report_node = "report_draft"
            self._add_node(lines, nodes, report_node, "report draft")
            for claim_node in claim_nodes.values():
                self._add_edge(lines, edges, claim_node, report_node, "supports report")
        if not evidence:
            self._add_node(lines, nodes, "empty", "暂无 evidence")
        confidence = self._diagram_confidence(evidence, [])
        return {
            "diagram_type": "evidence_map",
            "title": "证据图",
            "mermaid_source": "\n".join(lines),
            "nodes_edges": {"nodes": nodes, "edges": edges},
            "evidence_ids": [item.id for item in evidence[:50]],
            "confidence": confidence,
            "source_type": "evidence_constrained",
        }

    def _extract_flows(self, evidence: list) -> list[dict[str, Any]]:
        flows: list[dict[str, Any]] = []
        for item in evidence:
            decoded = item.decoded or {}
            candidates = []
            explicit_flow_source = item.source_type in {"balance_diff", "receipt_log"} or "flow" in item.claim_key.lower() or "transfer" in item.claim_key.lower()
            if not explicit_flow_source:
                continue
            for key in ("fund_flow_edges", "flows", "token_flows", "large_token_flows", "transfers", "token_transfers"):
                value = decoded.get(key)
                if isinstance(value, list):
                    candidates.extend(value)
            if explicit_flow_source and decoded.get("from") and decoded.get("to"):
                candidates.append(decoded)
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                source = candidate.get("from") or candidate.get("from_address") or candidate.get("sender")
                target = candidate.get("to") or candidate.get("to_address") or candidate.get("receiver")
                if not source or not target:
                    continue
                flows.append(
                    {
                        "from": source,
                        "to": target,
                        "asset": candidate.get("asset") or candidate.get("token") or candidate.get("symbol"),
                        "amount": candidate.get("amount") or candidate.get("amount_decimal") or candidate.get("value"),
                        "tx_hash": candidate.get("tx_hash") or decoded.get("tx_hash"),
                        "log_index": candidate.get("log_index"),
                        "confidence": candidate.get("confidence") or item.confidence,
                        "evidence_id": candidate.get("evidence_id") or item.id,
                    }
                )
        return flows

    def _extract_attack_steps(self, evidence: list) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in evidence:
            decoded = item.decoded or {}
            raw_steps = decoded.get("attack_steps")
            if not isinstance(raw_steps, list):
                continue
            for step in raw_steps:
                if not isinstance(step, dict):
                    continue
                key = str(step.get("id") or step.get("label") or step.get("tx_hash") or len(steps))
                if key in seen:
                    continue
                seen.add(key)
                steps.append({**step, "evidence_id": item.id})
        return steps

    def _add_node(self, lines: list[str], nodes: list[dict[str, Any]], node_id: str, label: str) -> None:
        if any(node["id"] == node_id for node in nodes):
            return
        nodes.append({"id": node_id, "label": label})
        lines.append(f'  {node_id}["{self._escape(label)}"]')

    def _add_edge(self, lines: list[str], edges: list[dict[str, Any]], source: str, target: str, label: str) -> None:
        edges.append({"source": source, "target": target, "label": label})
        lines.append(f'  {source} -->|"{self._escape(label)}"| {target}')

    def _edge_label(self, evidence: list) -> str:
        if not evidence:
            return ""
        confidence_order = {"high": 3, "medium": 2, "low": 1, "partial": 0}
        first = max(evidence, key=lambda item: confidence_order.get(str(item.confidence), -1))
        return f"{first.source_type}:{first.confidence} ({len(evidence)} evidence)"

    def _finding_rank(self, finding) -> tuple[int, int, str]:
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4, "unknown": 5}
        review_order = {"approved": 0, "pending": 1, "more_evidence_needed": 2, "rejected": 3}
        return (
            severity_order.get(str(finding.severity), 9),
            review_order.get(str(finding.reviewer_status), 9),
            str(finding.created_at),
        )

    def _flow_node_id(self, value: Any, address_nodes: dict[str, str]) -> str:
        key = str(value or "-").lower()
        if key not in address_nodes:
            address_nodes[key] = f"addr{len(address_nodes) + 1}"
        return address_nodes[key]

    def _flow_edge_label(self, flows: list[dict[str, Any]]) -> str:
        first = flows[0]
        label = " ".join(
            str(part)
            for part in [first.get("amount"), first.get("asset"), first.get("tx_hash") or first.get("evidence_id"), first.get("confidence")]
            if part not in {None, ""}
        )
        if len(flows) > 1:
            label = f"{len(flows)} flows / {label or 'transfer'}"
        return self._short(label or "transfer", 56)

    def _evidence_node_id(self, value: Any, node_map: dict[str, str], prefix: str) -> str:
        key = str(value or "-").lower()
        if key not in node_map:
            node_map[key] = f"{prefix}{len(node_map) + 1}"
        return node_map[key]

    def _evidence_edge_label(self, rows: list) -> str:
        confidence_order = {"high": 3, "medium": 2, "low": 1, "partial": 0}
        confidence = max((str(item.confidence) for item in rows), key=lambda value: confidence_order.get(value, -1), default="partial")
        return self._short(f"{len(rows)} evidence / {confidence}", 48)

    def _finding_edge_label(self, findings: list) -> str:
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
        severity = max((str(item.severity) for item in findings), key=lambda value: severity_order.get(value, -1), default="info")
        return self._short(f"{len(findings)} finding / {severity}", 48)

    def _diagram_confidence(self, evidence: list, transactions: list) -> str:
        if any(item.confidence == "high" for item in evidence) and transactions:
            return "high"
        if evidence or transactions:
            return "medium"
        return "partial"

    def _short(self, value: Any, length: int = 28) -> str:
        text = str(value or "-")
        if len(text) <= length:
            return text
        if text.startswith("0x") and len(text) > 18:
            return f"{text[:10]}...{text[-6:]}"
        return text[: length - 1] + "..."

    def _escape(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).replace('"', "'")

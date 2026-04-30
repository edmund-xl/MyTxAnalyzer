from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid4())


class Network(Base):
    __tablename__ = "networks"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    network_type: Mapped[str] = mapped_column(String(32), nullable=False, default="evm")
    chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    explorer_type: Mapped[str | None] = mapped_column(Text)
    explorer_base_url: Mapped[str | None] = mapped_column(Text)
    rpc_url_secret_ref: Mapped[str] = mapped_column(Text, nullable=False)
    explorer_api_key_secret_ref: Mapped[str | None] = mapped_column(Text)
    supports_trace_transaction: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_debug_trace_transaction: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_historical_eth_call: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    cases: Mapped[list["Case"]] = relationship(back_populates="network")


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        Index("idx_cases_status_updated", "status", "updated_at"),
        Index("idx_cases_network_updated", "network_key", "updated_at"),
        Index("idx_cases_updated", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    title: Mapped[str | None] = mapped_column(Text)
    network_key: Mapped[str] = mapped_column(ForeignKey("networks.key"), nullable=False)
    seed_type: Mapped[str] = mapped_column(String(32), nullable=False)
    seed_value: Mapped[str] = mapped_column(Text, nullable=False)
    time_window_hours: Mapped[int] = mapped_column(Integer, default=6)
    depth: Mapped[str] = mapped_column(String(32), default="quick")
    status: Mapped[str] = mapped_column(String(64), default="CREATED")
    severity: Mapped[str] = mapped_column(String(32), default="unknown")
    attack_type: Mapped[str | None] = mapped_column(Text)
    root_cause_one_liner: Mapped[str | None] = mapped_column(Text)
    loss_usd: Mapped[float | None] = mapped_column(Numeric)
    confidence: Mapped[str] = mapped_column(String(32), default="low")
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    network: Mapped[Network] = relationship(back_populates="cases")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    findings: Mapped[list["Finding"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    reports: Mapped[list["Report"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    diagrams: Mapped[list["DiagramSpec"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    job_runs: Mapped[list["JobRun"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("case_id", "tx_hash", name="uq_transactions_case_hash"),
        Index("idx_transactions_case", "case_id"),
        Index("idx_transactions_hash", "tx_hash"),
        Index("idx_transactions_phase", "case_id", "phase"),
        Index("idx_transactions_case_block", "case_id", "block_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    tx_hash: Mapped[str] = mapped_column(Text, nullable=False)
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    block_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tx_index: Mapped[int | None] = mapped_column(Integer)
    from_address: Mapped[str | None] = mapped_column(Text)
    to_address: Mapped[str | None] = mapped_column(Text)
    nonce: Mapped[int | None] = mapped_column(BigInteger)
    value_wei: Mapped[float | None] = mapped_column(Numeric)
    status: Mapped[int | None] = mapped_column(Integer)
    method_selector: Mapped[str | None] = mapped_column(String(10))
    method_name: Mapped[str | None] = mapped_column(Text)
    phase: Mapped[str] = mapped_column(Text, default="unknown")
    phase_confidence: Mapped[str] = mapped_column(String(32), default="low")
    artifact_status: Mapped[str] = mapped_column(String(32), default="pending")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    case: Mapped[Case] = relationship(back_populates="transactions")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="transaction")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="transaction")


class Address(Base):
    __tablename__ = "addresses"
    __table_args__ = (UniqueConstraint("case_id", "address", name="uq_addresses_case_address"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    address_type: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    code_hash: Mapped[str | None] = mapped_column(Text)
    first_seen_tx_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("case_id", "address", name="uq_contracts_case_address"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    proxy_type: Mapped[str | None] = mapped_column(Text)
    implementation_address: Mapped[str | None] = mapped_column(Text)
    contract_name: Mapped[str | None] = mapped_column(Text)
    verified_source: Mapped[bool] = mapped_column(Boolean, default=False)
    abi_available: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("case_id", "object_path", name="uq_artifacts_case_path"),
        Index("idx_artifacts_case", "case_id"),
        Index("idx_artifacts_tx", "tx_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    tx_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    producer: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="artifacts")
    transaction: Mapped[Transaction | None] = relationship(back_populates="artifacts")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("case_id", "source_type", "producer", "claim_key", "raw_path", name="uq_evidence_idempotency"),
        Index("idx_evidence_case", "case_id"),
        Index("idx_evidence_claim", "case_id", "claim_key"),
        Index("idx_evidence_source_type", "case_id", "source_type"),
        Index("idx_evidence_case_created", "case_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    tx_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    producer: Mapped[str] = mapped_column(Text, nullable=False)
    claim_key: Mapped[str] = mapped_column(Text, nullable=False)
    raw_path: Mapped[str | None] = mapped_column(Text)
    decoded: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[str] = mapped_column(String(32), default="low")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="evidence")
    transaction: Mapped[Transaction | None] = relationship(back_populates="evidence")


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        Index("idx_findings_case", "case_id"),
        Index("idx_findings_review", "case_id", "reviewer_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    finding_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="unknown")
    confidence: Mapped[str] = mapped_column(String(32), default="low")
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    falsification: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    reviewer_status: Mapped[str] = mapped_column(String(32), default="pending")
    reviewer_comment: Mapped[str | None] = mapped_column(Text)
    requires_reviewer: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(Text, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    case: Mapped[Case] = relationship(back_populates="findings")


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"

    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("case_id", "version", "format", name="uq_reports_case_version_format"),
        Index("idx_reports_case_version", "case_id", "version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    format: Mapped[str] = mapped_column(Text, default="markdown")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    object_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    evidence_coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    case: Mapped[Case] = relationship(back_populates="reports")
    sections: Mapped[list["ReportSection"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    exports: Mapped[list["ReportExport"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    diagrams: Mapped[list["DiagramSpec"]] = relationship(back_populates="report")


class DiagramSpec(Base):
    __tablename__ = "diagram_specs"
    __table_args__ = (
        UniqueConstraint("case_id", "diagram_type", name="uq_diagram_specs_case_type"),
        Index("idx_diagram_specs_case_type", "case_id", "diagram_type"),
        Index("idx_diagram_specs_report_type", "report_id", "diagram_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("reports.id", ondelete="SET NULL"))
    diagram_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    mermaid_source: Mapped[str] = mapped_column(Text, nullable=False)
    nodes_edges_json: Mapped[dict] = mapped_column("nodes_edges", JSON, default=dict)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(32), default="partial")
    source_type: Mapped[str] = mapped_column(Text, default="derived_from_evidence")
    object_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    case: Mapped[Case] = relationship(back_populates="diagrams")
    report: Mapped[Report | None] = relationship(back_populates="diagrams")


class ReportExport(Base):
    __tablename__ = "report_exports"
    __table_args__ = (
        UniqueConstraint("report_id", "format", name="uq_report_exports_report_format"),
        Index("idx_report_exports_report", "report_id"),
        Index("idx_report_exports_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    object_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    report: Mapped[Report] = relationship(back_populates="exports")


class ReportSection(Base):
    __tablename__ = "report_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    section_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    coverage: Mapped[float] = mapped_column(Numeric, default=0)
    status: Mapped[str] = mapped_column(Text, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[Report] = relationship(back_populates="sections")


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        Index("idx_job_runs_case", "case_id"),
        Index("idx_job_runs_status", "case_id", "status"),
        Index("idx_job_runs_case_created", "case_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="job_runs")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("idx_workflow_runs_case_created", "case_id", "created_at"),
        Index("idx_workflow_runs_status", "status"),
        UniqueConstraint("workflow_id", name="uq_workflow_runs_workflow_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    case: Mapped[Case] = relationship(back_populates="workflow_runs")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    actor: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
EVM_TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
SUI_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{1,64}$")


class SeedType(StrEnum):
    transaction = "transaction"
    address = "address"
    contract = "contract"
    alert = "alert"


class AnalysisDepth(StrEnum):
    quick = "quick"
    full = "full"
    full_replay = "full_replay"


class CaseStatus(StrEnum):
    CREATED = "CREATED"
    ENV_CHECKING = "ENV_CHECKING"
    ENV_CHECKED = "ENV_CHECKED"
    DISCOVERING_TRANSACTIONS = "DISCOVERING_TRANSACTIONS"
    TRANSACTIONS_DISCOVERED = "TRANSACTIONS_DISCOVERED"
    PULLING_ARTIFACTS = "PULLING_ARTIFACTS"
    ARTIFACTS_PULLED = "ARTIFACTS_PULLED"
    DECODING = "DECODING"
    DECODED = "DECODED"
    BUILDING_EVIDENCE = "BUILDING_EVIDENCE"
    EVIDENCE_BUILT = "EVIDENCE_BUILT"
    RUNNING_FORENSICS = "RUNNING_FORENSICS"
    FORENSICS_DONE = "FORENSICS_DONE"
    RUNNING_RCA_AGENT = "RUNNING_RCA_AGENT"
    RCA_DONE = "RCA_DONE"
    DRAFTING_REPORT = "DRAFTING_REPORT"
    REPORT_DRAFTED = "REPORT_DRAFTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"
    unknown = "unknown"


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    partial = "partial"


class ReviewStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    more_evidence_needed = "more_evidence_needed"


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    partial = "partial"


class ReportStatus(StrEnum):
    draft = "draft"
    under_review = "under_review"
    published = "published"
    archived = "archived"


class CaseCreate(BaseModel):
    title: str | None = None
    network_key: str
    seed_type: SeedType
    seed_value: str
    time_window_hours: int = Field(default=6, ge=1, le=168)
    depth: AnalysisDepth = AnalysisDepth.quick
    modules: list[str] = Field(default_factory=list)
    language: str = "zh-CN"

    @field_validator("seed_value")
    @classmethod
    def seed_value_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("seed_value is required")
        return value

    @model_validator(mode="after")
    def seed_value_matches_seed_type(self) -> "CaseCreate":
        network_key = self.network_key.lower()
        value = self.seed_value.strip()

        if self.seed_type == SeedType.address:
            if EVM_TX_HASH_RE.fullmatch(value):
                raise ValueError("seed_value looks like an EVM transaction hash; use seed_type=transaction")
            if network_key == "sui":
                if not SUI_ADDRESS_RE.fullmatch(value):
                    raise ValueError("Sui address seed_value must be 0x followed by 1 to 64 hex characters")
            elif not EVM_ADDRESS_RE.fullmatch(value):
                raise ValueError("address seed_value must be a 42-character EVM address")

        return self


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str | None
    network_key: str
    seed_type: SeedType
    seed_value: str
    time_window_hours: int
    depth: AnalysisDepth
    status: CaseStatus
    severity: Severity
    attack_type: str | None = None
    root_cause_one_liner: str | None = None
    loss_usd: float | None = None
    confidence: Confidence
    language: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class CaseSummaryResponse(BaseModel):
    total_cases: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    review_queue: int
    high_severity: int


class CaseDetailSummaryResponse(BaseModel):
    transaction_count: int
    evidence_count: int
    finding_count: int
    report_count: int
    diagram_count: int
    job_count: int


class NetworkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    network_type: str = "evm"
    chain_id: int
    explorer_type: str | None = None
    explorer_base_url: str | None = None
    rpc_url_secret_ref: str
    explorer_api_key_secret_ref: str | None = None
    supports_trace_transaction: bool
    supports_debug_trace_transaction: bool
    supports_historical_eth_call: bool


class TransactionCreate(BaseModel):
    tx_hash: str
    phase: str = "manual"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    tx_hash: str
    block_number: int | None = None
    block_timestamp: datetime | None = None
    tx_index: int | None = None
    from_address: str | None = None
    to_address: str | None = None
    nonce: int | None = None
    value_wei: float | None = None
    status: int | None = None
    method_selector: str | None = None
    method_name: str | None = None
    phase: str
    phase_confidence: Confidence
    artifact_status: str
    metadata_json: dict[str, Any] = Field(default_factory=dict, serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime


class TimelineItem(BaseModel):
    tx_id: str
    tx_hash: str
    timestamp: datetime | None = None
    block_number: int | None = None
    phase: str
    from_address: str | None = None
    to_address: str | None = None
    method: str | None = None
    confidence: str
    evidence_count: int


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    tx_id: str | None = None
    source_type: str
    producer: str
    claim_key: str
    raw_path: str | None = None
    decoded: dict[str, Any]
    confidence: Confidence
    created_at: datetime


class FindingCreate(BaseModel):
    title: str
    finding_type: str
    severity: Severity = Severity.info
    confidence: Confidence = Confidence.low
    claim: str
    rationale: str | None = None
    falsification: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    requires_reviewer: bool = True
    created_by: str = "system"


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    title: str
    finding_type: str
    severity: Severity
    confidence: Confidence
    claim: str
    rationale: str | None = None
    falsification: str | None = None
    evidence_ids: list[str]
    reviewer_status: ReviewStatus
    reviewer_comment: str | None = None
    requires_reviewer: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class FindingReviewRequest(BaseModel):
    reviewer_status: ReviewStatus
    reviewer_comment: str | None = None
    confidence: Confidence | None = None


class ReportCreate(BaseModel):
    language: str | None = None
    format: Literal["markdown", "json"] = "markdown"


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    version: int
    language: str
    format: str
    status: ReportStatus
    object_path: str | None = None
    content_hash: str | None = None
    evidence_coverage: dict[str, Any]
    metadata_json: dict[str, Any] = Field(default_factory=dict, serialization_alias="metadata")
    created_by: str | None = None
    reviewed_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ReportDetail(ReportResponse):
    content: str | dict[str, Any] | None = None


class DiagramSpecResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    report_id: str | None = None
    diagram_type: str
    title: str
    mermaid_source: str
    nodes_edges_json: dict[str, Any] = Field(default_factory=dict, serialization_alias="nodes_edges")
    evidence_ids: list[str]
    confidence: Confidence
    source_type: str
    object_path: str | None = None
    content_hash: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ReportExportCreate(BaseModel):
    format: Literal["pdf"] = "pdf"


class ReportExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    report_id: str
    format: str
    status: str
    object_path: str | None = None
    content_hash: str | None = None
    error: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict, serialization_alias="metadata")
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class JobRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    job_name: str
    status: JobStatus
    input: dict[str, Any]
    output: dict[str, Any]
    error: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime


class WorkflowRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    workflow_id: str
    mode: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict, serialization_alias="metadata")
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkerResult(BaseModel):
    case_id: str
    worker_name: str
    status: Literal["success", "partial", "failed"]
    summary: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class RunCaseResponse(BaseModel):
    workflow_id: str
    status: str
    mode: str
    workflow_run_id: str | None = None


class TxAnalyzerRuntimeHealth(BaseModel):
    ready: bool
    root: str
    root_exists: bool
    script_exists: bool
    python_executable: str
    python_ok: bool
    required_packages: dict[str, bool]
    error: str | None = None

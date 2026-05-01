from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ClaimType = Literal[
    "fact",
    "inference",
    "hypothesis",
    "root_cause",
    "loss",
    "boundary",
    "remediation",
]
ClaimConfidence = Literal["high", "medium", "low", "partial"]


class EvidenceRef(BaseModel):
    evidence_id: str
    source_type: str | None = None
    producer: str | None = None
    claim_key: str | None = None
    raw_path: str | None = None


class ReportClaim(BaseModel):
    claim_id: str
    section: str
    claim_type: ClaimType
    text: str
    confidence: ClaimConfidence
    support_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    reasoning: str = ""
    falsification: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlternativeHypothesis(BaseModel):
    hypothesis_id: str
    name: str
    status: Literal["accepted", "rejected", "insufficient_evidence", "secondary_factor"]
    support_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str
    confidence: ClaimConfidence = "medium"


class FinancialImpactItem(BaseModel):
    item_id: str
    category: Literal["confirmed_loss", "probable_loss", "unpriced_movement", "out_of_scope"]
    asset: str
    amount_raw: str | None = None
    amount_display: str | None = None
    usd_value: str | None = None
    price_source: str | None = None
    support_evidence_ids: list[str] = Field(default_factory=list)
    confidence: ClaimConfidence
    notes: str | None = None


class ClaimGraph(BaseModel):
    case_id: str
    report_version: int
    renderer_family: str
    claims: list[ReportClaim] = Field(default_factory=list)
    alternative_hypotheses: list[AlternativeHypothesis] = Field(default_factory=list)
    financial_impact: list[FinancialImpactItem] = Field(default_factory=list)
    global_boundaries: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportQualityIssue(BaseModel):
    issue_id: str
    severity: Literal["blocking", "warning", "info"]
    rule_id: str
    message: str
    section: str | None = None
    claim_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    recommendation: str | None = None


class ReportQualityResult(BaseModel):
    case_id: str
    report_version: int
    score: int
    blocking_issues: list[ReportQualityIssue] = Field(default_factory=list)
    warnings: list[ReportQualityIssue] = Field(default_factory=list)
    infos: list[ReportQualityIssue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

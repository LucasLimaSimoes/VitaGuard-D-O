from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class RawStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"


class EvidenceRef(BaseModel):
    """Evidence claimed by the LLM before deterministic validation."""

    chunk_id: str
    page_number: int = Field(ge=1)
    excerpt: str = Field(min_length=4, max_length=600)
    section: str | None = Field(default=None, max_length=200)


class ScalarFact(BaseModel):
    field_id: str = Field(max_length=100)
    status: RawStatus
    raw_value: str | None = Field(default=None, max_length=800)
    normalized_value: str | None = Field(default=None, max_length=500)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)


class FinancialFact(BaseModel):
    field_id: str
    original_name: str
    raw_value: str
    kind: Literal["MONEY", "PERCENTAGE", "DURATION", "NUMBER", "TEXT"]
    numeric_value: float | None = None
    currency: str | None = None
    unit: str | None = None
    normalized_text: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CoreExtraction(BaseModel):
    policy_id_hint: str | None = None
    scalar_facts: list[ScalarFact] = Field(default_factory=list, max_length=40)
    financial_facts: list[FinancialFact] = Field(default_factory=list, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class EmbeddedFinancialFact(BaseModel):
    field_id: str = "coverage_sublimit"
    original_name: str
    raw_value: str
    kind: Literal["MONEY", "PERCENTAGE", "DURATION", "NUMBER", "TEXT"]
    numeric_value: float | None = None
    currency: str | None = None
    unit: str | None = None
    normalized_text: str | None = None
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ItemFact(BaseModel):
    canonical_id: str | None = None
    original_name: str
    description: str | None = None
    category: str | None = None
    conditions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    applies_to: list[str] = Field(default_factory=list)
    financials: list[EmbeddedFinancialFact] = Field(default_factory=list)
    extraction_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    normalization_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class RiskExtraction(BaseModel):
    coverages: list[ItemFact] = Field(default_factory=list, max_length=60)
    extensions: list[ItemFact] = Field(default_factory=list, max_length=60)
    exclusions: list[ItemFact] = Field(default_factory=list, max_length=80)
    warnings: list[str] = Field(default_factory=list)


class CoveragesExtensionsExtraction(BaseModel):
    """Smaller long-document stage for coverages + extensions only."""

    coverages: list[ItemFact] = Field(default_factory=list, max_length=50)
    extensions: list[ItemFact] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list)


class ExclusionsExtraction(BaseModel):
    """Smaller long-document stage for exclusions only."""

    exclusions: list[ItemFact] = Field(default_factory=list, max_length=60)
    warnings: list[str] = Field(default_factory=list)


class DefinitionFact(BaseModel):
    canonical_term: str | None = None
    original_term: str
    definition_text: str
    extraction_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    normalization_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ClauseFact(BaseModel):
    canonical_id: str | None = None
    original_name: str
    summary: str | None = None
    conditions: list[str] = Field(default_factory=list)
    extraction_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    normalization_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class SemanticExtraction(BaseModel):
    definitions: list[DefinitionFact] = Field(default_factory=list, max_length=100)
    clauses: list[ClauseFact] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list)


class DefinitionsExtraction(BaseModel):
    definitions: list[DefinitionFact] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list)


class ClausesExtraction(BaseModel):
    clauses: list[ClauseFact] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list)


class EvidenceIssue(BaseModel):
    extractor: str
    object_type: str
    object_name: str
    chunk_id: str
    page_number: int
    reason: str
    excerpt: str


class EvidenceRepair(BaseModel):
    extractor: str
    object_type: str
    object_name: str
    chunk_id: str
    page_number: int
    original_excerpt: str
    repaired_excerpt: str
    similarity: float = Field(ge=0.0, le=1.0)


class EvidenceRecovery(BaseModel):
    extractor: str
    object_type: str
    object_name: str
    original_chunk_id: str
    original_page_number: int
    original_excerpt: str
    recovered_chunk_id: str | None = None
    recovered_page_number: int
    recovered_excerpt: str
    matched_term: str


class EvidenceValidationReport(BaseModel):
    total_claims: int = 0
    valid_claims: int = 0
    invalid_claims: int = 0
    repaired_claims: int = 0
    recovered_claims: int = 0
    issues: list[EvidenceIssue] = Field(default_factory=list)
    repairs: list[EvidenceRepair] = Field(default_factory=list)
    recoveries: list[EvidenceRecovery] = Field(default_factory=list)

    @property
    def validity_rate(self) -> float:
        return self.valid_claims / self.total_claims if self.total_claims else 1.0


class StructuredExtractionRun(BaseModel):
    project_version: str = "0.5B.5"
    document_id: str
    source_name: str
    provider: str
    model: str
    selected_chunks: dict[str, list[str]] = Field(default_factory=dict)
    core: CoreExtraction
    risk: RiskExtraction
    semantic: SemanticExtraction
    evidence_report: EvidenceValidationReport
    policy_json: dict
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "StructuredExtractionRun":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

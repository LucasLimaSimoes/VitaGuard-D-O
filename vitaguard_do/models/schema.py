from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, model_validator


class ExtractionStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CONFLICTING = "CONFLICTING"


class Evidence(BaseModel):
    document_id: str
    page: int = Field(ge=1)
    section: str | None = None
    excerpt: str
    chunk_id: str | None = None


T = TypeVar("T")


class CandidateValue(BaseModel, Generic[T]):
    value: T
    evidence: list[Evidence] = Field(default_factory=list)


class ExtractedField(BaseModel, Generic[T]):
    status: ExtractionStatus
    value: T | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    candidates: list[CandidateValue[T]] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_state(self):
        if self.status == ExtractionStatus.FOUND and self.value is None:
            raise ValueError("FOUND requires a value.")
        if self.status in {ExtractionStatus.NOT_FOUND, ExtractionStatus.NOT_APPLICABLE} and self.value is not None:
            raise ValueError(f"{self.status.value} must not contain a value.")
        if self.status in {ExtractionStatus.AMBIGUOUS, ExtractionStatus.CONFLICTING} and not self.candidates:
            raise ValueError(f"{self.status.value} requires candidates.")
        return self


class ValueKind(str, Enum):
    MONEY = "MONEY"
    PERCENTAGE = "PERCENTAGE"
    DURATION = "DURATION"
    NUMBER = "NUMBER"
    TEXT = "TEXT"


class NormalizedValue(BaseModel):
    kind: ValueKind
    numeric_value: Decimal | None = None
    currency: str | None = None
    unit: str | None = None
    normalized_text: str | None = None
    raw_text: str


class DocumentType(str, Enum):
    ISSUED_POLICY = "ISSUED_POLICY"
    GENERAL_CONDITIONS = "GENERAL_CONDITIONS"
    SPECIAL_CONDITIONS = "SPECIAL_CONDITIONS"
    ENDORSEMENT = "ENDORSEMENT"
    SCHEDULE = "SCHEDULE"
    PROPOSAL = "PROPOSAL"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class DocumentOrigin(str, Enum):
    PUBLIC_REAL = "PUBLIC_REAL"
    SYNTHETIC_VITAGUARD = "SYNTHETIC_VITAGUARD"
    USER_PROVIDED = "USER_PROVIDED"
    UNKNOWN = "UNKNOWN"


class SourceDocument(BaseModel):
    document_id: str
    source_file: str
    sha256: str | None = None
    page_count: int | None = Field(default=None, ge=1)
    language: str | None = None
    document_type: DocumentType = DocumentType.UNKNOWN
    origin: DocumentOrigin = DocumentOrigin.UNKNOWN


class PolicyIdentification(BaseModel):
    insurer: ExtractedField[str]
    product_name: ExtractedField[str]
    susep_process: ExtractedField[str]
    policy_number: ExtractedField[str]
    insured: ExtractedField[str]
    policyholder: ExtractedField[str]
    document_version: ExtractedField[str]


class DateRange(BaseModel):
    start: date | None = None
    end: date | None = None


class ContractualTerms(BaseModel):
    policy_period: ExtractedField[DateRange]
    currency: ExtractedField[str]
    premium: ExtractedField[NormalizedValue]
    retroactive_date: ExtractedField[date]
    extended_reporting_period: ExtractedField[NormalizedValue]
    geographic_scope: ExtractedField[str]
    jurisdiction: ExtractedField[str]
    coverage_trigger: ExtractedField[str]
    # Stable comparison codes. The source-facing values/evidence above remain untouched.
    geographic_scope_canonical: str | None = None
    jurisdiction_canonical: str | None = None
    coverage_trigger_canonical: str | None = None


class SourceItem(BaseModel):
    canonical_id: str | None = None
    original_name: str
    description: str | None = None
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    normalization_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)


class Limit(SourceItem):
    value: NormalizedValue
    applies_to: list[str] = Field(default_factory=list)


class Deductible(SourceItem):
    value: NormalizedValue
    applies_to: list[str] = Field(default_factory=list)


class Coverage(SourceItem):
    category: str | None = None
    conditions: list[str] = Field(default_factory=list)
    limits: list[Limit] = Field(default_factory=list)
    deductibles: list[Deductible] = Field(default_factory=list)


class Extension(SourceItem):
    conditions: list[str] = Field(default_factory=list)
    limits: list[Limit] = Field(default_factory=list)
    deductibles: list[Deductible] = Field(default_factory=list)


class Exclusion(SourceItem):
    exceptions: list[str] = Field(default_factory=list)
    applies_to: list[str] = Field(default_factory=list)


class Definition(BaseModel):
    canonical_term: str | None = None
    original_term: str
    definition_text: str
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    normalization_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)


class Clause(SourceItem):
    category: str | None = None
    summary: str | None = None
    conditions: list[str] = Field(default_factory=list)


class ExtractionMethod(str, Enum):
    NATIVE_TEXT = "NATIVE_TEXT"
    OCR = "OCR"
    MULTIMODAL = "MULTIMODAL"
    HYBRID = "HYBRID"


class ExtractionMetadata(BaseModel):
    schema_version: str = "0.4"
    extraction_method: ExtractionMethod
    extractor_model: str | None = None
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PolicyRecord(BaseModel):
    policy_id: str
    source_documents: list[SourceDocument] = Field(min_length=1)
    identification: PolicyIdentification
    contractual_terms: ContractualTerms
    policy_limits: list[Limit] = Field(default_factory=list)
    policy_deductibles: list[Deductible] = Field(default_factory=list)
    coverages: list[Coverage] = Field(default_factory=list)
    extensions: list[Extension] = Field(default_factory=list)
    exclusions: list[Exclusion] = Field(default_factory=list)
    definitions: list[Definition] = Field(default_factory=list)
    clauses: list[Clause] = Field(default_factory=list)
    extraction: ExtractionMetadata


class PolicyPortfolio(BaseModel):
    policies: list[PolicyRecord] = Field(min_length=2)

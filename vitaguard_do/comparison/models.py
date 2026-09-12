from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from vitaguard_do.models.schema import Evidence, ExtractionStatus


class ComparisonStatus(str, Enum):
    EQUAL = "EQUAL"
    DIFFERENT = "DIFFERENT"
    ONLY_IN_SOME = "ONLY_IN_SOME"
    ALL_MISSING = "ALL_MISSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class HarmonizedPresenceStatus(str, Enum):
    PRESENT_IN_ALL = "PRESENT_IN_ALL"
    PRESENT_IN_SOME = "PRESENT_IN_SOME"
    ABSENT_IN_ALL = "ABSENT_IN_ALL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ComparisonValue(BaseModel):
    policy_id: str
    policy_label: str
    present: bool
    extraction_status: ExtractionStatus | None = None
    value: Any = None
    canonical_value: Any = None
    source_name: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    notes: str | None = None


class ComparisonRow(BaseModel):
    section: str
    field_id: str
    label: str
    kind: str
    status: ComparisonStatus
    values: list[ComparisonValue]
    comparison_basis: str
    present_count: int = 0
    policy_count: int = 0
    present_policy_ids: list[str] = Field(default_factory=list)
    missing_policy_ids: list[str] = Field(default_factory=list)
    scope_ids: list[str] = Field(default_factory=list)
    comparison_concept_id: str | None = None
    comparison_concept_label: str | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def presence_fraction(self) -> str:
        return f"{self.present_count}/{self.policy_count}" if self.policy_count else "0/0"


class HarmonizedConceptValue(BaseModel):
    policy_id: str
    policy_label: str
    present: bool
    matched_members: list[str] = Field(default_factory=list)
    source_names: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class HarmonizedConcept(BaseModel):
    comparison_concept_id: str
    label: str
    description: str
    status: HarmonizedPresenceStatus
    values: list[HarmonizedConceptValue]
    present_count: int = 0
    policy_count: int = 0
    present_policy_ids: list[str] = Field(default_factory=list)
    missing_policy_ids: list[str] = Field(default_factory=list)
    member_rows: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def presence_fraction(self) -> str:
        return f"{self.present_count}/{self.policy_count}" if self.policy_count else "0/0"


class ComparisonSummary(BaseModel):
    policy_count: int
    row_count: int
    equal: int = 0
    different: int = 0
    only_in_some: int = 0
    all_missing: int = 0
    needs_review: int = 0

    @property
    def material_difference_count(self) -> int:
        return self.different + self.only_in_some + self.needs_review


class ComparisonReport(BaseModel):
    comparison_version: str = "0.6.4"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    policy_ids: list[str] = Field(min_length=2)
    policy_labels: dict[str, str]
    rows: list[ComparisonRow]
    harmonized_concepts: list[HarmonizedConcept] = Field(default_factory=list)
    summary: ComparisonSummary

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class SetMetric(BaseModel):
    expected: int
    extracted: int
    true_positive: int
    precision: float
    recall: float
    f1: float
    missing_ids: list[str] = Field(default_factory=list)
    extra_ids: list[str] = Field(default_factory=list)


class ExtractionEvaluation(BaseModel):
    policy_name: str
    scalar_correct: int
    scalar_total: int
    scalar_accuracy: float
    financial_correct: int
    financial_total: int
    financial_accuracy: float
    canonical_sets: dict[str, SetMetric]
    canonical_macro_f1: float
    nested_sublimit_correct: int
    nested_sublimit_total: int
    nested_sublimit_accuracy: float
    evidence_valid: int
    evidence_total: int
    evidence_validity_rate: float
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "ExtractionEvaluation":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

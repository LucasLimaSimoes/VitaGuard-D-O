from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field


class DemoBundle(BaseModel):
    root: str
    files: dict[str, str]
    migrated_from: dict[str, str | None] = Field(default_factory=dict)

    def paths(self) -> dict[str, Path]:
        return {key: Path(value) for key, value in self.files.items()}


class PolicyOverview(BaseModel):
    policy_id: str
    insurer: str
    product: str
    source_file: str
    document_origin: str
    document_type: str
    coverage_count: int = 0
    extension_count: int = 0
    exclusion_count: int = 0
    definition_count: int = 0
    clause_count: int = 0
    warning_count: int = 0
    error_count: int = 0

    @property
    def label(self) -> str:
        return f"{self.insurer} — {self.product}"


class ProcessingStage(BaseModel):
    id: str
    label: str
    completed: bool = True
    detail: str | None = None


class ReviewItem(BaseModel):
    section: str
    field_id: str
    label: str
    presence_fraction: str
    notes: list[str] = Field(default_factory=list)

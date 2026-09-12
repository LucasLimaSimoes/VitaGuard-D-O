from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class ConceptMember:
    section: str
    field_id: str


@dataclass(frozen=True)
class ComparisonConceptSpec:
    id: str
    label: str
    description: str
    members: tuple[ConceptMember, ...]


@dataclass(frozen=True)
class HarmonizationConfig:
    version: str
    concepts: tuple[ComparisonConceptSpec, ...]

    def concept_for(self, section: str, field_id: str) -> ComparisonConceptSpec | None:
        for concept in self.concepts:
            if any(member.section == section and member.field_id == field_id for member in concept.members):
                return concept
        return None


def load_harmonization_config(path: str | Path | None = None) -> HarmonizationConfig:
    if path is None:
        path = Path(__file__).with_name("harmonization.yaml")
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    concepts: list[ComparisonConceptSpec] = []
    for item in raw.get("concepts", []):
        concepts.append(ComparisonConceptSpec(
            id=str(item["id"]),
            label=str(item["label"]),
            description=str(item.get("description") or ""),
            members=tuple(
                ConceptMember(section=str(member["section"]), field_id=str(member["field_id"]))
                for member in item.get("members", [])
            ),
        ))
    return HarmonizationConfig(version=str(raw.get("version") or "unknown"), concepts=tuple(concepts))

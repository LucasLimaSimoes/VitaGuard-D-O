from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from vitaguard_do.extraction.deterministic import canonicalize_document_version
from vitaguard_do.extraction.normalization import canonicalize_contractual_field
from vitaguard_do.extraction.models import EvidenceValidationReport
from vitaguard_do.models.schema import ExtractionStatus, PolicyRecord


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


class RealGoldFactResult(BaseModel):
    id: str
    kind: str
    passed: bool
    expected: str | None = None
    actual: str | None = None
    evidence_page_ok: bool | None = None
    actual_evidence_pages: list[int] = Field(default_factory=list)
    notes: str | None = None


class RealGoldEvaluation(BaseModel):
    source_id: str
    total_facts: int
    passed_facts: int
    fact_accuracy: float
    evidence_page_checks: int
    evidence_page_hits: int
    evidence_page_accuracy: float
    deterministic_evidence_validity: float
    results: list[RealGoldFactResult]
    taxonomy_gaps: list[str] = Field(default_factory=list)


def _resolve_path(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        current = getattr(current, part)
    return current


def _canonical_items(policy: PolicyRecord, collection: str):
    return getattr(policy, collection)


def _canonical_value(item: Any, collection: str) -> str | None:
    if collection == "definitions":
        return item.canonical_term
    return item.canonical_id


def _item_evidence_pages(item: Any) -> list[int]:
    return sorted({ev.page for ev in getattr(item, "evidence", [])})


def evaluate_real_gold(
    policy: PolicyRecord,
    *,
    gold_path: str | Path,
    evidence_report: EvidenceValidationReport,
) -> RealGoldEvaluation:
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    results: list[RealGoldFactResult] = []
    evidence_checks = 0
    evidence_hits = 0

    for fact in gold["facts"]:
        kind = fact["kind"]
        expected_pages = set(fact.get("evidence_pages", []))
        page_ok: bool | None = None
        actual_pages: list[int] = []

        if kind == "field_contains":
            field = _resolve_path(policy, fact["path"])
            actual = field.value if field.status == ExtractionStatus.FOUND else None
            if fact["path"] == "identification.document_version":
                expected_version = canonicalize_document_version(fact["expected"])
                actual_version = canonicalize_document_version(str(actual) if actual is not None else None)
                passed = (
                    field.status == ExtractionStatus.FOUND
                    and expected_version is not None
                    and expected_version == actual_version
                )
            else:
                expected_canonical = canonicalize_contractual_field(fact["path"], fact["expected"])
                actual_canonical = canonicalize_contractual_field(
                    fact["path"], str(actual) if actual is not None else None
                )
                if expected_canonical is not None:
                    passed = (
                        field.status == ExtractionStatus.FOUND
                        and expected_canonical == actual_canonical
                    )
                else:
                    passed = field.status == ExtractionStatus.FOUND and _norm(fact["expected"]) in _norm(actual)
            actual_pages = sorted({ev.page for ev in field.evidence})
            if expected_pages:
                evidence_checks += 1
                page_ok = bool(expected_pages.intersection(actual_pages))
                evidence_hits += int(page_ok)
            results.append(RealGoldFactResult(
                id=fact["id"], kind=kind, passed=passed,
                expected=fact["expected"], actual=str(actual) if actual is not None else None,
                evidence_page_ok=page_ok, actual_evidence_pages=actual_pages,
            ))

        elif kind == "field_status":
            field = _resolve_path(policy, fact["path"])
            actual_status = field.status.value
            passed = actual_status == fact["expected_status"]
            results.append(RealGoldFactResult(
                id=fact["id"], kind=kind, passed=passed,
                expected=fact["expected_status"], actual=actual_status,
            ))

        elif kind == "canonical_present":
            items = _canonical_items(policy, fact["collection"])
            matches = [
                item for item in items
                if _canonical_value(item, fact["collection"]) == fact["canonical_id"]
            ]
            passed = bool(matches)
            if matches:
                actual_pages = sorted({p for item in matches for p in _item_evidence_pages(item)})
            if expected_pages:
                evidence_checks += 1
                page_ok = bool(expected_pages.intersection(actual_pages))
                evidence_hits += int(page_ok)
            results.append(RealGoldFactResult(
                id=fact["id"], kind=kind, passed=passed,
                expected=fact["canonical_id"],
                actual=fact["canonical_id"] if passed else None,
                evidence_page_ok=page_ok, actual_evidence_pages=actual_pages,
            ))

        else:
            raise ValueError(f"Gold fact kind nao suportado: {kind}")

    taxonomy_gaps: list[str] = []
    for item in policy.coverages:
        if not item.canonical_id:
            taxonomy_gaps.append(f"coverage: {item.original_name}")
    for item in policy.extensions:
        if not item.canonical_id:
            taxonomy_gaps.append(f"extension: {item.original_name}")
    for item in policy.exclusions:
        if not item.canonical_id:
            taxonomy_gaps.append(f"exclusion: {item.original_name}")
    for item in policy.definitions:
        if not item.canonical_term:
            taxonomy_gaps.append(f"definition: {item.original_term}")
    for item in policy.clauses:
        if not item.canonical_id:
            taxonomy_gaps.append(f"clause: {item.original_name}")

    passed = sum(1 for item in results if item.passed)
    total = len(results)
    return RealGoldEvaluation(
        source_id=gold["source_id"],
        total_facts=total,
        passed_facts=passed,
        fact_accuracy=passed / total if total else 1.0,
        evidence_page_checks=evidence_checks,
        evidence_page_hits=evidence_hits,
        evidence_page_accuracy=evidence_hits / evidence_checks if evidence_checks else 1.0,
        deterministic_evidence_validity=evidence_report.validity_rate,
        results=results,
        taxonomy_gaps=sorted(set(taxonomy_gaps)),
    )

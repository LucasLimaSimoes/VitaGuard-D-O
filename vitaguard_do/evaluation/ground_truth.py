from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from pathlib import Path

from vitaguard_do.extraction.models import EvidenceValidationReport
from vitaguard_do.models.schema import ExtractionStatus, PolicyRecord

from .models import ExtractionEvaluation, SetMetric


def _norm_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _field_value(field):
    return field.value if field.status == ExtractionStatus.FOUND else None


def _scalar_pairs(policy: PolicyRecord) -> dict[str, object]:
    i = policy.identification
    c = policy.contractual_terms
    period = _field_value(c.policy_period)
    premium = _field_value(c.premium)
    erp = _field_value(c.extended_reporting_period)
    return {
        "insurer": _field_value(i.insurer),
        "product_name": _field_value(i.product_name),
        "policy_number": _field_value(i.policy_number),
        "insured": _field_value(i.insured),
        "policyholder": _field_value(i.policyholder),
        "document_version": _field_value(i.document_version),
        "policy_period_start": period.start if period else None,
        "policy_period_end": period.end if period else None,
        "currency": _field_value(c.currency),
        "premium": premium.numeric_value if premium else None,
        "retroactive_date": _field_value(c.retroactive_date),
        "erp_numeric": erp.numeric_value if erp else None,
        "erp_unit": erp.unit if erp else None,
    }


def _equal_scalar(a: object, b: object) -> bool:
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        try:
            return Decimal(str(a)) == Decimal(str(b))
        except Exception:
            return False
    if hasattr(a, "isoformat") and hasattr(b, "isoformat"):
        return a.isoformat() == b.isoformat()
    if isinstance(a, str) or isinstance(b, str):
        return _norm_text(None if a is None else str(a)) == _norm_text(None if b is None else str(b))
    return a == b




def _decimal_key(value: object | None) -> str:
    """Canonical numeric string for benchmark keys (1, 1.0 and 1.00 are equal)."""
    if value is None:
        return ""
    try:
        dec = Decimal(str(value))
        if dec == 0:
            return "0"
        return format(dec.normalize(), "f")
    except Exception:
        return str(value)


def _financial_keys(policy: PolicyRecord) -> set[tuple[str, str, tuple[str, ...]]]:
    keys = set()
    for item in policy.policy_limits:
        keys.add((
            item.canonical_id or "",
            _decimal_key(item.value.numeric_value) if item.value.numeric_value is not None else _norm_text(item.value.raw_text) or "",
            tuple(sorted(item.applies_to)),
        ))
    for item in policy.policy_deductibles:
        keys.add((
            item.canonical_id or "",
            _decimal_key(item.value.numeric_value) if item.value.numeric_value is not None else _norm_text(item.value.raw_text) or "",
            tuple(sorted(item.applies_to)),
        ))
    return keys


def _canonical_ids(policy: PolicyRecord, category: str) -> set[str]:
    if category == "coverages":
        return {x.canonical_id for x in policy.coverages if x.canonical_id}
    if category == "extensions":
        return {x.canonical_id for x in policy.extensions if x.canonical_id}
    if category == "exclusions":
        return {x.canonical_id for x in policy.exclusions if x.canonical_id}
    if category == "definitions":
        return {x.canonical_term for x in policy.definitions if x.canonical_term}
    if category == "clauses":
        return {x.canonical_id for x in policy.clauses if x.canonical_id}
    raise KeyError(category)


def _set_metric(expected: set[str], extracted: set[str]) -> SetMetric:
    tp = len(expected & extracted)
    precision = tp / len(extracted) if extracted else (1.0 if not expected else 0.0)
    recall = tp / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return SetMetric(
        expected=len(expected),
        extracted=len(extracted),
        true_positive=tp,
        precision=precision,
        recall=recall,
        f1=f1,
        missing_ids=sorted(expected - extracted),
        extra_ids=sorted(extracted - expected),
    )


def _nested_sublimits(policy: PolicyRecord) -> set[tuple[str, str, str]]:
    result = set()
    for category, items in (("coverage", policy.coverages), ("extension", policy.extensions)):
        for item in items:
            parent = item.canonical_id or ""
            for lim in item.limits:
                if lim.canonical_id == "coverage_sublimit":
                    value = _decimal_key(lim.value.numeric_value) if lim.value.numeric_value is not None else (_norm_text(lim.value.raw_text) or "")
                    result.add((category, parent, value))
    return result


def evaluate_policy(
    extracted: PolicyRecord,
    expected: PolicyRecord,
    *,
    policy_name: str,
    evidence_report: EvidenceValidationReport,
) -> ExtractionEvaluation:
    a = _scalar_pairs(extracted)
    b = _scalar_pairs(expected)
    scalar_total = len(b)
    scalar_correct = sum(_equal_scalar(a.get(k), v) for k, v in b.items())

    expected_fin = _financial_keys(expected)
    extracted_fin = _financial_keys(extracted)
    financial_correct = len(expected_fin & extracted_fin)
    financial_total = len(expected_fin)

    categories = ("coverages", "extensions", "exclusions", "definitions", "clauses")
    metrics = {
        category: _set_metric(_canonical_ids(expected, category), _canonical_ids(extracted, category))
        for category in categories
    }
    macro_f1 = sum(m.f1 for m in metrics.values()) / len(metrics)

    expected_sub = _nested_sublimits(expected)
    extracted_sub = _nested_sublimits(extracted)
    nested_correct = len(expected_sub & extracted_sub)
    nested_total = len(expected_sub)

    notes = []
    extra_fin = extracted_fin - expected_fin
    missing_fin = expected_fin - extracted_fin
    if missing_fin:
        notes.append(f"Financial facts missing: {sorted(missing_fin)}")
    if extra_fin:
        notes.append(f"Unexpected financial facts: {sorted(extra_fin)}")

    return ExtractionEvaluation(
        policy_name=policy_name,
        scalar_correct=scalar_correct,
        scalar_total=scalar_total,
        scalar_accuracy=scalar_correct / scalar_total if scalar_total else 1.0,
        financial_correct=financial_correct,
        financial_total=financial_total,
        financial_accuracy=financial_correct / financial_total if financial_total else 1.0,
        canonical_sets=metrics,
        canonical_macro_f1=macro_f1,
        nested_sublimit_correct=nested_correct,
        nested_sublimit_total=nested_total,
        nested_sublimit_accuracy=nested_correct / nested_total if nested_total else 1.0,
        evidence_valid=evidence_report.valid_claims,
        evidence_total=evidence_report.total_claims,
        evidence_validity_rate=evidence_report.validity_rate,
        notes=notes,
    )


def save_evaluation(report: ExtractionEvaluation, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path

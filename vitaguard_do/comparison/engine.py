from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterable

from pydantic import BaseModel

from vitaguard_do.comparison.models import (
    ComparisonReport,
    ComparisonRow,
    ComparisonStatus,
    ComparisonSummary,
    ComparisonValue,
    HarmonizedConcept,
    HarmonizedConceptValue,
    HarmonizedPresenceStatus,
)
from vitaguard_do.models.schema import (
    Clause,
    Coverage,
    Deductible,
    Definition,
    Evidence,
    Exclusion,
    Extension,
    ExtractedField,
    ExtractionStatus,
    Limit,
    NormalizedValue,
    PolicyPortfolio,
    PolicyRecord,
)
from vitaguard_do.taxonomy.loader import TaxonomyRegistry, load_taxonomies, normalize_alias
from vitaguard_do.contractual_normalization import canonicalize_contractual_field
from vitaguard_do.comparison.harmonization import HarmonizationConfig, load_harmonization_config


SCALAR_SPECS = (
    ("identification", "insurer", "Seguradora"),
    ("identification", "product_name", "Produto"),
    ("identification", "susep_process", "Processo SUSEP"),
    ("identification", "policy_number", "Número da apólice"),
    ("identification", "insured", "Segurado"),
    ("identification", "policyholder", "Estipulante / tomador"),
    ("identification", "document_version", "Versão do documento"),
    ("contractual_terms", "policy_period", "Vigência"),
    ("contractual_terms", "currency", "Moeda"),
    ("contractual_terms", "premium", "Prêmio"),
    ("contractual_terms", "retroactive_date", "Data retroativa"),
    ("contractual_terms", "extended_reporting_period", "Prazo complementar"),
    ("contractual_terms", "geographic_scope", "Âmbito geográfico"),
    ("contractual_terms", "jurisdiction", "Jurisdição"),
    ("contractual_terms", "coverage_trigger", "Base de cobertura"),
)

COLLECTION_SPECS = (
    ("policy_limits", "Limites da apólice", "financial", "financial_fields"),
    ("policy_deductibles", "Franquias da apólice", "financial", "financial_fields"),
    ("coverages", "Coberturas", "item", "coverages"),
    ("extensions", "Extensões", "item", "extensions"),
    ("exclusions", "Exclusões", "item", "exclusions"),
    ("definitions", "Definições", "definition", "definitions"),
    ("clauses", "Cláusulas", "item", "clauses"),
)


def _text_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _decimal_key(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Decimal):
        return _decimal_key(value)
    if isinstance(value, list):
        return [_jsonable(x) for x in value]
    if isinstance(value, tuple):
        return [_jsonable(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _stable(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _normalized_value_key(value: NormalizedValue) -> dict[str, Any]:
    return {
        "kind": value.kind.value,
        "numeric_value": _decimal_key(value.numeric_value),
        "currency": value.currency.upper() if value.currency else None,
        "unit": _text_key(value.unit) if value.unit else None,
        "normalized_text": _text_key(value.normalized_text) if value.normalized_text else None,
    }


def _canonical_scalar(policy: PolicyRecord, section: str, name: str, value: Any) -> Any:
    if section == "contractual_terms":
        canonical_attr = {
            "geographic_scope": "geographic_scope_canonical",
            "jurisdiction": "jurisdiction_canonical",
            "coverage_trigger": "coverage_trigger_canonical",
        }.get(name)
        if canonical_attr:
            canonical = getattr(policy.contractual_terms, canonical_attr, None)
            if canonical:
                return canonical

            # Backward compatibility: validated PolicyRecords from older extraction
            # versions may predate the *_canonical fields. Canonicalize the raw
            # structured value at comparison time rather than forcing re-extraction.
            fallback = canonicalize_contractual_field(
                f"{section}.{name}",
                str(value) if value is not None else None,
            )
            if fallback:
                return fallback

    if isinstance(value, NormalizedValue):
        return _normalized_value_key(value)
    if isinstance(value, BaseModel):
        return _jsonable(value)
    if isinstance(value, str):
        return _text_key(value)
    return _jsonable(value)


def _policy_label(policy: PolicyRecord) -> str:
    insurer = policy.identification.insurer.value if policy.identification.insurer.status == ExtractionStatus.FOUND else None
    product = policy.identification.product_name.value if policy.identification.product_name.status == ExtractionStatus.FOUND else None
    if insurer and product:
        return f"{insurer} — {product}"
    if insurer:
        return insurer
    if product:
        return product
    return policy.policy_id


def _scalar_status(values: list[ComparisonValue]) -> ComparisonStatus:
    statuses = [v.extraction_status for v in values]
    if any(s in {ExtractionStatus.AMBIGUOUS, ExtractionStatus.CONFLICTING} for s in statuses):
        return ComparisonStatus.NEEDS_REVIEW

    found = [v for v in values if v.extraction_status == ExtractionStatus.FOUND]
    if not found:
        return ComparisonStatus.ALL_MISSING
    if len(found) != len(values):
        return ComparisonStatus.ONLY_IN_SOME

    keys = {_stable(v.canonical_value) for v in found}
    return ComparisonStatus.EQUAL if len(keys) == 1 else ComparisonStatus.DIFFERENT



def _presence_metadata(values: list[ComparisonValue]) -> dict[str, Any]:
    present_ids = [v.policy_id for v in values if v.present]
    missing_ids = [v.policy_id for v in values if not v.present]
    return {
        "present_count": len(present_ids),
        "policy_count": len(values),
        "present_policy_ids": present_ids,
        "missing_policy_ids": missing_ids,
    }


def _scalar_rows(portfolio: PolicyPortfolio, labels: dict[str, str]) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    for section, field_name, label in SCALAR_SPECS:
        values: list[ComparisonValue] = []
        for policy in portfolio.policies:
            parent = getattr(policy, section)
            field: ExtractedField[Any] = getattr(parent, field_name)
            raw_value = _jsonable(field.value)
            canonical = None
            if field.status == ExtractionStatus.FOUND:
                canonical = _canonical_scalar(policy, section, field_name, field.value)
            elif field.status in {ExtractionStatus.AMBIGUOUS, ExtractionStatus.CONFLICTING}:
                canonical = [_jsonable(c.value) for c in field.candidates]
            values.append(ComparisonValue(
                policy_id=policy.policy_id,
                policy_label=labels[policy.policy_id],
                present=field.status == ExtractionStatus.FOUND,
                extraction_status=field.status,
                value=raw_value,
                canonical_value=canonical,
                evidence=list(field.evidence),
                notes=field.notes,
            ))
        rows.append(ComparisonRow(
            section=section,
            field_id=field_name,
            label=label,
            kind="scalar",
            status=_scalar_status(values),
            values=values,
            comparison_basis="valor canônico quando disponível; caso contrário normalização determinística do valor estruturado",
            **_presence_metadata(values),
        ))
    return rows


def _item_key(item: Any, taxonomy_category: str, registry: TaxonomyRegistry) -> tuple[str, str]:
    if isinstance(item, Definition):
        canonical_id = item.canonical_term
        original = item.original_term
    else:
        canonical_id = getattr(item, "canonical_id", None)
        original = getattr(item, "original_name", "")

    if canonical_id:
        tax = registry.get_item(taxonomy_category, canonical_id)
        return canonical_id, tax.label if tax else original or canonical_id

    resolved = registry.resolve(taxonomy_category, original) if original else None
    if resolved:
        return resolved.id, resolved.label

    fallback = normalize_alias(original) or "unnamed"
    return f"unmapped:{fallback}", original or fallback


def _canonical_scope_ids(applies_to: Iterable[str], registry: TaxonomyRegistry) -> list[str]:
    scopes: list[str] = []
    for raw in applies_to:
        raw = str(raw)
        direct = registry.get_item("coverages", raw)
        if direct:
            scopes.append(direct.id)
            continue
        resolved = registry.resolve("coverages", raw)
        if resolved:
            scopes.append(resolved.id)
            continue
        scopes.append(f"unmapped:{normalize_alias(raw) or _text_key(raw) or 'scope'}")
    return sorted(set(scopes))


def _scope_label(scope_id: str, registry: TaxonomyRegistry) -> str:
    if scope_id.startswith("unmapped:"):
        return scope_id.removeprefix("unmapped:").replace("_", " ")
    item = registry.get_item("coverages", scope_id)
    return item.label if item else scope_id


def _financial_payload(item: Limit | Deductible, registry: TaxonomyRegistry) -> dict[str, Any]:
    return {
        "value": _normalized_value_key(item.value),
        "applies_to": _canonical_scope_ids(item.applies_to, registry),
    }


def _nested_financial(items: Iterable[Limit | Deductible], registry: TaxonomyRegistry) -> list[dict[str, Any]]:
    payloads = [_financial_payload(x, registry) for x in items]
    return sorted(payloads, key=_stable)


def _item_payload(item: Any, registry: TaxonomyRegistry) -> Any:
    if isinstance(item, (Limit, Deductible)):
        return _financial_payload(item, registry)
    if isinstance(item, Coverage):
        return {
            "category": _text_key(item.category) if item.category else None,
            "conditions": sorted(_text_key(x) for x in item.conditions),
            "limits": _nested_financial(item.limits, registry),
            "deductibles": _nested_financial(item.deductibles, registry),
        }
    if isinstance(item, Extension):
        return {
            "conditions": sorted(_text_key(x) for x in item.conditions),
            "limits": _nested_financial(item.limits, registry),
            "deductibles": _nested_financial(item.deductibles, registry),
        }
    if isinstance(item, Exclusion):
        return {
            "exceptions": sorted(_text_key(x) for x in item.exceptions),
            "applies_to": sorted(_text_key(x) for x in item.applies_to),
        }
    if isinstance(item, Definition):
        return {"definition_text": _text_key(item.definition_text)}
    if isinstance(item, Clause):
        return {
            "category": _text_key(item.category) if item.category else None,
            "summary": _text_key(item.summary) if item.summary else None,
            "conditions": sorted(_text_key(x) for x in item.conditions),
        }
    return _jsonable(item)


def _item_evidence(item: Any) -> list[Evidence]:
    return list(getattr(item, "evidence", []) or [])


def _item_original_name(item: Any) -> str:
    if isinstance(item, Definition):
        return item.original_term
    return getattr(item, "original_name", "")


def _collection_identity(
    item: Any,
    *,
    attr: str,
    taxonomy_category: str,
    registry: TaxonomyRegistry,
) -> tuple[str, str, list[str], str]:
    base_key, base_label = _item_key(item, taxonomy_category, registry)
    scopes: list[str] = []
    if isinstance(item, (Limit, Deductible)):
        scopes = _canonical_scope_ids(item.applies_to, registry)
    if scopes:
        scope_token = "+".join(scopes)
        key = f"{base_key}::scope={scope_token}"
        label = f"{base_label} — " + " + ".join(_scope_label(x, registry) for x in scopes)
    else:
        key = base_key
        label = base_label
    return key, label, scopes, base_key


def _collection_rows(
    portfolio: PolicyPortfolio,
    labels: dict[str, str],
    registry: TaxonomyRegistry,
    harmonization: HarmonizationConfig,
) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []

    for attr, section_label, kind, taxonomy_category in COLLECTION_SPECS:
        grouped_by_policy: dict[str, dict[str, list[Any]]] = {}
        labels_by_key: dict[str, str] = {}
        scopes_by_key: dict[str, list[str]] = {}
        base_key_by_key: dict[str, str] = {}
        all_keys: set[str] = set()

        for policy in portfolio.policies:
            groups: dict[str, list[Any]] = defaultdict(list)
            for item in getattr(policy, attr):
                key, item_label, scope_ids, base_key = _collection_identity(
                    item, attr=attr, taxonomy_category=taxonomy_category, registry=registry
                )
                groups[key].append(item)
                labels_by_key.setdefault(key, item_label)
                scopes_by_key.setdefault(key, scope_ids)
                base_key_by_key.setdefault(key, base_key)
                all_keys.add(key)
            grouped_by_policy[policy.policy_id] = groups

        for key in sorted(all_keys, key=lambda x: (x.startswith("unmapped:"), labels_by_key.get(x, x).casefold())):
            values: list[ComparisonValue] = []
            duplicate = False
            duplicate_notes: list[str] = []
            for policy in portfolio.policies:
                items = grouped_by_policy[policy.policy_id].get(key, [])
                if not items:
                    values.append(ComparisonValue(
                        policy_id=policy.policy_id,
                        policy_label=labels[policy.policy_id],
                        present=False,
                        extraction_status=ExtractionStatus.NOT_FOUND,
                    ))
                    continue

                original_names = sorted({_item_original_name(item) for item in items if _item_original_name(item)})
                if len(items) > 1:
                    duplicate = True
                    names = "; ".join(original_names) if original_names else "nomes originais não disponíveis"
                    duplicate_notes.append(
                        f"{labels[policy.policy_id]}: {len(items)} ocorrências para a mesma chave comparativa '{key}' — {names}"
                    )
                payloads = [_item_payload(item, registry) for item in items]
                evidence = [ev for item in items for ev in _item_evidence(item)]
                values.append(ComparisonValue(
                    policy_id=policy.policy_id,
                    policy_label=labels[policy.policy_id],
                    present=True,
                    extraction_status=ExtractionStatus.FOUND,
                    value=[_jsonable(item) for item in items] if len(items) > 1 else _jsonable(items[0]),
                    canonical_value=payloads if len(payloads) > 1 else payloads[0],
                    source_name=" / ".join(original_names) or None,
                    evidence=evidence,
                    notes=(
                        f"{len(items)} ocorrências para a mesma chave comparativa: "
                        + ("; ".join(original_names) if original_names else "nomes não disponíveis")
                        if len(items) > 1 else None
                    ),
                ))

            present = [v for v in values if v.present]
            if duplicate:
                status = ComparisonStatus.NEEDS_REVIEW
            elif len(present) != len(values):
                status = ComparisonStatus.ONLY_IN_SOME
            else:
                payload_keys = {_stable(v.canonical_value) for v in present}
                status = ComparisonStatus.EQUAL if len(payload_keys) == 1 else ComparisonStatus.DIFFERENT

            base_key = base_key_by_key.get(key, key)
            concept = harmonization.concept_for(attr, base_key)
            rows.append(ComparisonRow(
                section=attr,
                field_id=key,
                label=labels_by_key.get(key, key),
                kind=kind,
                status=status,
                values=values,
                comparison_basis=(
                    "alinhamento por canonical_id + applies_to canonico para itens financeiros; diferenças materiais usam valores/condições/exceções estruturadas"
                    if kind == "financial"
                    else (
                        "alinhamento por canonical_id; diferenças materiais usam limites/franquias/condições/exceções estruturadas"
                        if kind != "definition"
                        else "alinhamento por termo canônico; comparação determinística do texto normalizado da definição"
                    )
                ),
                **_presence_metadata(values),
                scope_ids=scopes_by_key.get(key, []),
                comparison_concept_id=concept.id if concept else None,
                comparison_concept_label=concept.label if concept else None,
                notes=(
                    [section_label]
                    + (["chave comparativa duplicada em ao menos uma apólice"] if duplicate else [])
                    + duplicate_notes
                ),
            ))

    return rows


def _build_harmonized_concepts(
    rows: list[ComparisonRow],
    portfolio: PolicyPortfolio,
    labels: dict[str, str],
    harmonization: HarmonizationConfig,
) -> list[HarmonizedConcept]:
    result: list[HarmonizedConcept] = []
    for concept in harmonization.concepts:
        member_pairs = {(m.section, m.field_id) for m in concept.members}
        member_rows = [
            row for row in rows
            if (row.section, row.field_id.split("::scope=", 1)[0]) in member_pairs
        ]
        values: list[HarmonizedConceptValue] = []
        any_review = any(row.status == ComparisonStatus.NEEDS_REVIEW for row in member_rows)
        for policy in portfolio.policies:
            matched: list[str] = []
            source_names: list[str] = []
            evidence: list[Evidence] = []
            for row in member_rows:
                value = next(v for v in row.values if v.policy_id == policy.policy_id)
                if not value.present:
                    continue
                matched.append(f"{row.section}/{row.field_id}")
                if value.source_name:
                    source_names.extend(x.strip() for x in value.source_name.split(" / ") if x.strip())
                evidence.extend(value.evidence)
            values.append(HarmonizedConceptValue(
                policy_id=policy.policy_id,
                policy_label=labels[policy.policy_id],
                present=bool(matched),
                matched_members=sorted(set(matched)),
                source_names=sorted(set(source_names)),
                evidence=evidence,
            ))
        present_ids = [v.policy_id for v in values if v.present]
        missing_ids = [v.policy_id for v in values if not v.present]
        if any_review:
            status = HarmonizedPresenceStatus.NEEDS_REVIEW
        elif not present_ids:
            status = HarmonizedPresenceStatus.ABSENT_IN_ALL
        elif len(present_ids) == len(values):
            status = HarmonizedPresenceStatus.PRESENT_IN_ALL
        else:
            status = HarmonizedPresenceStatus.PRESENT_IN_SOME
        result.append(HarmonizedConcept(
            comparison_concept_id=concept.id,
            label=concept.label,
            description=concept.description,
            status=status,
            values=values,
            present_count=len(present_ids),
            policy_count=len(values),
            present_policy_ids=present_ids,
            missing_policy_ids=missing_ids,
            member_rows=sorted(f"{r.section}/{r.field_id}" for r in member_rows),
            notes=[
                "Família comparativa para navegação semântica; não afirma equivalência contratual entre os membros."
            ],
        ))
    return result


def compare_portfolio(
    portfolio: PolicyPortfolio,
    *,
    registry: TaxonomyRegistry | None = None,
    harmonization: HarmonizationConfig | None = None,
) -> ComparisonReport:
    if registry is None:
        registry = load_taxonomies()
    if harmonization is None:
        harmonization = load_harmonization_config()

    labels = {policy.policy_id: _policy_label(policy) for policy in portfolio.policies}
    rows = _scalar_rows(portfolio, labels)
    rows.extend(_collection_rows(portfolio, labels, registry, harmonization))
    harmonized_concepts = _build_harmonized_concepts(rows, portfolio, labels, harmonization)

    counts = defaultdict(int)
    for row in rows:
        counts[row.status.value] += 1

    summary = ComparisonSummary(
        policy_count=len(portfolio.policies),
        row_count=len(rows),
        equal=counts[ComparisonStatus.EQUAL.value],
        different=counts[ComparisonStatus.DIFFERENT.value],
        only_in_some=counts[ComparisonStatus.ONLY_IN_SOME.value],
        all_missing=counts[ComparisonStatus.ALL_MISSING.value],
        needs_review=counts[ComparisonStatus.NEEDS_REVIEW.value],
    )
    return ComparisonReport(
        policy_ids=[p.policy_id for p in portfolio.policies],
        policy_labels=labels,
        rows=rows,
        harmonized_concepts=harmonized_concepts,
        summary=summary,
    )


def compare_policies(
    policies: Iterable[PolicyRecord],
    *,
    registry: TaxonomyRegistry | None = None,
    harmonization: HarmonizationConfig | None = None,
) -> ComparisonReport:
    return compare_portfolio(
        PolicyPortfolio(policies=list(policies)),
        registry=registry,
        harmonization=harmonization,
    )

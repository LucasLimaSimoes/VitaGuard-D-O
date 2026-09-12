from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from vitaguard_do.ingestion.models import IngestedDocument
from vitaguard_do.models.schema import (
    Clause,
    ContractualTerms,
    Coverage,
    DateRange,
    Deductible,
    Definition,
    DocumentOrigin,
    DocumentType,
    Exclusion,
    ExtractedField,
    ExtractionMetadata,
    ExtractionMethod,
    ExtractionStatus,
    Extension,
    Limit,
    NormalizedValue,
    PolicyIdentification,
    PolicyRecord,
    SourceDocument,
    ValueKind,
)
from vitaguard_do.taxonomy.loader import TaxonomyRegistry
from .normalization import canonicalize_coverage_trigger, canonicalize_geographic_scope, canonicalize_jurisdiction

from .deterministic import canonicalize_document_version, find_document_version, find_susep_process
from .evidence import EvidenceValidator
from .models import (
    CoreExtraction,
    EvidenceValidationReport,
    FinancialFact,
    ItemFact,
    RawStatus,
    RiskExtraction,
    ScalarFact,
    SemanticExtraction,
)


def _domain_status(status: RawStatus) -> ExtractionStatus:
    return {
        RawStatus.FOUND: ExtractionStatus.FOUND,
        RawStatus.NOT_FOUND: ExtractionStatus.NOT_FOUND,
        RawStatus.AMBIGUOUS: ExtractionStatus.AMBIGUOUS,
    }[status]


def _date_or_none(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _decimal(value: float | int | str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _value_kind(kind: str) -> ValueKind:
    try:
        return ValueKind(kind)
    except ValueError:
        return ValueKind.TEXT


def _normalized_value_from_financial(fact: FinancialFact) -> NormalizedValue:
    return NormalizedValue(
        kind=_value_kind(fact.kind),
        numeric_value=_decimal(fact.numeric_value),
        currency=fact.currency,
        unit=fact.unit,
        normalized_text=fact.normalized_text,
        raw_text=fact.raw_value,
    )


def _duration_from_scalar(fact: ScalarFact) -> NormalizedValue | None:
    raw = fact.raw_value or fact.normalized_value
    if not raw:
        return None
    import re

    match = re.search(r"(\d+(?:[.,]\d+)?)", raw)
    numeric = Decimal(match.group(1).replace(",", ".")) if match else None
    low = raw.casefold()
    if "mes" in low:
        unit = "months"
    elif "ano" in low:
        unit = "years"
    elif "dia" in low:
        unit = "days"
    else:
        unit = None
    return NormalizedValue(
        kind=ValueKind.DURATION,
        numeric_value=numeric,
        unit=unit,
        normalized_text=fact.normalized_value or raw,
        raw_text=fact.raw_value or raw,
    )


def _resolve_id(registry: TaxonomyRegistry, category: str, canonical_id: str | None, original_name: str) -> tuple[str | None, float]:
    if canonical_id and registry.has_id(category, canonical_id):
        return canonical_id, 1.0
    resolved = registry.resolve(category, original_name)
    if resolved:
        return resolved.id, 0.9
    return None, 0.0


def assemble_policy(
    *,
    document: IngestedDocument,
    core: CoreExtraction,
    risk: RiskExtraction,
    semantic: SemanticExtraction,
    registry: TaxonomyRegistry,
    provider_model: str,
) -> tuple[PolicyRecord, EvidenceValidationReport]:
    validator = EvidenceValidator(document)
    report = EvidenceValidationReport()

    scalar_map = {fact.field_id: fact for fact in core.scalar_facts}

    def scalar_field(field_id: str) -> ExtractedField[str]:
        fact = scalar_map.get(field_id)

        deterministic = None
        if field_id == "susep_process":
            deterministic = find_susep_process(document)
        elif field_id == "document_version":
            deterministic = find_document_version(document)

        if fact is None:
            if deterministic is not None:
                return ExtractedField[str](
                    status=ExtractionStatus.FOUND,
                    value=deterministic.value,
                    confidence=1.0,
                    evidence=[deterministic.evidence],
                    notes="Preenchido por extracao deterministica sobre o texto-fonte.",
                )
            return ExtractedField[str](status=ExtractionStatus.NOT_FOUND)

        status = _domain_status(fact.status)
        value = fact.normalized_value or fact.raw_value
        if field_id == "document_version" and value:
            value = canonicalize_document_version(value) or value

        recovery_terms = [
            term for term in (value, fact.raw_value, fact.normalized_value) if term
        ]
        evidence = validator.validate_many(
            fact.evidence,
            extractor="core",
            object_type="scalar",
            object_name=field_id,
            report=report,
            recovery_terms=recovery_terms,
        )
        if deterministic is not None and not evidence:
            evidence = [deterministic.evidence]

        if status == ExtractionStatus.FOUND and not value:
            status = ExtractionStatus.NOT_FOUND

        # Structured identifiers/version markers are safe candidates for a
        # deterministic fallback when the LLM omits them. The source evidence
        # is copied from the PDF's raw page text, never invented.
        if (status != ExtractionStatus.FOUND or not value) and deterministic is not None:
            return ExtractedField[str](
                status=ExtractionStatus.FOUND,
                value=deterministic.value,
                confidence=1.0,
                evidence=[deterministic.evidence],
                notes="LLM nao forneceu valor util; preenchido por extracao deterministica.",
            )

        if status == ExtractionStatus.AMBIGUOUS:
            return ExtractedField[str](
                status=ExtractionStatus.NOT_FOUND,
                confidence=fact.confidence,
                evidence=evidence,
                notes=f"LLM marked AMBIGUOUS: {fact.notes or ''}".strip(),
            )
        return ExtractedField[str](
            status=status,
            value=value if status == ExtractionStatus.FOUND else None,
            confidence=fact.confidence,
            evidence=evidence,
            notes=fact.notes,
        )

    identification = PolicyIdentification(
        insurer=scalar_field("insurer"),
        product_name=scalar_field("product_name"),
        susep_process=scalar_field("susep_process"),
        policy_number=scalar_field("policy_number"),
        insured=scalar_field("insured"),
        policyholder=scalar_field("policyholder"),
        document_version=scalar_field("document_version"),
    )

    start_fact = scalar_map.get("policy_period_start")
    end_fact = scalar_map.get("policy_period_end")
    start_date = _date_or_none((start_fact.normalized_value or start_fact.raw_value) if start_fact else None)
    end_date = _date_or_none((end_fact.normalized_value or end_fact.raw_value) if end_fact else None)
    period_evidence = []
    period_confidence = None
    if start_fact:
        period_evidence.extend(validator.validate_many(
            start_fact.evidence, extractor="core", object_type="scalar", object_name="policy_period_start", report=report
        ))
    if end_fact:
        period_evidence.extend(validator.validate_many(
            end_fact.evidence, extractor="core", object_type="scalar", object_name="policy_period_end", report=report
        ))
    if start_fact or end_fact:
        period_confidence = min([f.confidence for f in (start_fact, end_fact) if f is not None])
    policy_period = ExtractedField[DateRange](
        status=ExtractionStatus.FOUND if start_date and end_date else ExtractionStatus.NOT_FOUND,
        value=DateRange(start=start_date, end=end_date) if start_date and end_date else None,
        confidence=period_confidence,
        evidence=period_evidence,
    )

    def date_field(field_id: str) -> ExtractedField[date]:
        fact = scalar_map.get(field_id)
        if not fact:
            return ExtractedField[date](status=ExtractionStatus.NOT_FOUND)
        evidence = validator.validate_many(
            fact.evidence, extractor="core", object_type="scalar", object_name=field_id, report=report
        )
        parsed = _date_or_none(fact.normalized_value or fact.raw_value)
        return ExtractedField[date](
            status=ExtractionStatus.FOUND if parsed else ExtractionStatus.NOT_FOUND,
            value=parsed,
            confidence=fact.confidence,
            evidence=evidence,
            notes=fact.notes,
        )

    def duration_field(field_id: str) -> ExtractedField[NormalizedValue]:
        fact = scalar_map.get(field_id)
        if not fact:
            return ExtractedField[NormalizedValue](status=ExtractionStatus.NOT_FOUND)
        evidence = validator.validate_many(
            fact.evidence, extractor="core", object_type="scalar", object_name=field_id, report=report
        )
        value = _duration_from_scalar(fact)
        return ExtractedField[NormalizedValue](
            status=ExtractionStatus.FOUND if value else ExtractionStatus.NOT_FOUND,
            value=value,
            confidence=fact.confidence,
            evidence=evidence,
            notes=fact.notes,
        )

    financials = core.financial_facts

    def first_financial(field_id: str) -> FinancialFact | None:
        return next((fact for fact in financials if fact.field_id == field_id), None)

    def financial_field(field_id: str) -> ExtractedField[NormalizedValue]:
        fact = first_financial(field_id)
        if not fact:
            return ExtractedField[NormalizedValue](status=ExtractionStatus.NOT_FOUND)
        evidence = validator.validate_many(
            fact.evidence, extractor="core", object_type="financial", object_name=field_id, report=report,
            recovery_terms=[fact.original_name, fact.raw_value, fact.normalized_text or ""],
        )
        return ExtractedField[NormalizedValue](
            status=ExtractionStatus.FOUND,
            value=_normalized_value_from_financial(fact),
            confidence=fact.confidence,
            evidence=evidence,
        )

    geographic_scope = scalar_field("geographic_scope")
    jurisdiction = scalar_field("jurisdiction")
    coverage_trigger = scalar_field("coverage_trigger")
    contractual_terms = ContractualTerms(
        policy_period=policy_period,
        currency=scalar_field("currency"),
        premium=financial_field("premium"),
        retroactive_date=date_field("retroactive_date"),
        extended_reporting_period=duration_field("extended_reporting_period"),
        geographic_scope=geographic_scope,
        jurisdiction=jurisdiction,
        coverage_trigger=coverage_trigger,
        geographic_scope_canonical=canonicalize_geographic_scope(geographic_scope.value),
        jurisdiction_canonical=canonicalize_jurisdiction(jurisdiction.value),
        coverage_trigger_canonical=canonicalize_coverage_trigger(coverage_trigger.value),
    )

    policy_limits: list[Limit] = []
    policy_deductibles: list[Deductible] = []
    for fact in financials:
        evidence = validator.validate_many(
            fact.evidence, extractor="core", object_type="financial", object_name=fact.original_name, report=report,
            recovery_terms=[fact.original_name, fact.raw_value, fact.normalized_text or ""],
        )
        canonical_id, norm_conf = _resolve_id(registry, "financial_fields", fact.field_id, fact.original_name)
        if fact.field_id in {"maximum_guarantee_limit", "aggregate_limit"}:
            policy_limits.append(Limit(
                canonical_id=canonical_id or fact.field_id,
                original_name=fact.original_name,
                extraction_confidence=fact.confidence,
                normalization_confidence=norm_conf or fact.confidence,
                evidence=evidence,
                value=_normalized_value_from_financial(fact),
                applies_to=fact.applies_to,
            ))
        elif fact.field_id == "deductible":
            policy_deductibles.append(Deductible(
                canonical_id=canonical_id or "deductible",
                original_name=fact.original_name,
                extraction_confidence=fact.confidence,
                normalization_confidence=norm_conf or fact.confidence,
                evidence=evidence,
                value=_normalized_value_from_financial(fact),
                applies_to=fact.applies_to,
            ))

    def item_evidence(
        item: ItemFact,
        extractor: str,
        obj_type: str,
        taxonomy_category: str,
        canonical_id: str | None,
    ):
        terms = registry.recovery_terms(taxonomy_category, canonical_id, item.original_name)
        evidence = validator.validate_many(
            item.evidence,
            extractor=extractor,
            object_type=obj_type,
            object_name=item.original_name,
            report=report,
            recovery_terms=terms,
            prefer_formal_heading=True,
        )
        if not evidence:
            support = validator.find_support(terms, prefer_formal_heading=True)
            if support is not None:
                evidence = [support[0]]
        return evidence

    def item_limits(item: ItemFact, parent_id: str | None, obj_type: str) -> list[Limit]:
        result: list[Limit] = []
        for fin in item.financials:
            evidence = validator.validate_many(
                fin.evidence,
                extractor="risk",
                object_type=f"{obj_type}_financial",
                object_name=f"{item.original_name}: {fin.original_name}",
                report=report,
                recovery_terms=[fin.original_name, fin.raw_value, fin.normalized_text or ""],
            )
            cid, norm_conf = _resolve_id(registry, "financial_fields", fin.field_id, fin.original_name)
            result.append(Limit(
                canonical_id=cid or fin.field_id,
                original_name=fin.original_name,
                extraction_confidence=fin.confidence,
                normalization_confidence=norm_conf or fin.confidence,
                evidence=evidence,
                value=NormalizedValue(
                    kind=_value_kind(fin.kind),
                    numeric_value=_decimal(fin.numeric_value),
                    currency=fin.currency,
                    unit=fin.unit,
                    normalized_text=fin.normalized_text,
                    raw_text=fin.raw_value,
                ),
                applies_to=[parent_id] if parent_id else [],
            ))
        return result

    coverages: list[Coverage] = []
    for item in risk.coverages:
        cid, norm_conf = _resolve_id(registry, "coverages", item.canonical_id, item.original_name)
        coverages.append(Coverage(
            canonical_id=cid,
            original_name=item.original_name,
            description=item.description,
            extraction_confidence=item.extraction_confidence,
            normalization_confidence=max(norm_conf, item.normalization_confidence if cid else 0.0),
            evidence=item_evidence(item, "risk", "coverage", "coverages", cid),
            category=item.category or "MAIN_COVERAGE",
            conditions=item.conditions,
            limits=item_limits(item, cid, "coverage"),
            deductibles=[],
        ))

    extensions: list[Extension] = []
    for item in risk.extensions:
        cid, norm_conf = _resolve_id(registry, "extensions", item.canonical_id, item.original_name)
        extensions.append(Extension(
            canonical_id=cid,
            original_name=item.original_name,
            description=item.description,
            extraction_confidence=item.extraction_confidence,
            normalization_confidence=max(norm_conf, item.normalization_confidence if cid else 0.0),
            evidence=item_evidence(item, "risk", "extension", "extensions", cid),
            conditions=item.conditions,
            limits=item_limits(item, cid, "extension"),
            deductibles=[],
        ))

    exclusions: list[Exclusion] = []
    for item in risk.exclusions:
        cid, norm_conf = _resolve_id(registry, "exclusions", item.canonical_id, item.original_name)
        exclusions.append(Exclusion(
            canonical_id=cid,
            original_name=item.original_name,
            description=item.description,
            extraction_confidence=item.extraction_confidence,
            normalization_confidence=max(norm_conf, item.normalization_confidence if cid else 0.0),
            evidence=item_evidence(item, "risk", "exclusion", "exclusions", cid),
            exceptions=item.exceptions,
            applies_to=item.applies_to,
        ))

    definitions: list[Definition] = []
    for item in semantic.definitions:
        cid, norm_conf = _resolve_id(registry, "definitions", item.canonical_term, item.original_term)
        terms = registry.recovery_terms("definitions", cid, item.original_term)
        evidence = validator.validate_many(
            item.evidence,
            extractor="semantic",
            object_type="definition",
            object_name=item.original_term,
            report=report,
            recovery_terms=terms,
            prefer_formal_heading=True,
        )
        if not evidence:
            support = validator.find_support(terms, prefer_formal_heading=True)
            if support is not None:
                evidence = [support[0]]
        definitions.append(Definition(
            canonical_term=cid,
            original_term=item.original_term,
            definition_text=item.definition_text,
            extraction_confidence=item.extraction_confidence,
            normalization_confidence=max(norm_conf, item.normalization_confidence if cid else 0.0),
            evidence=evidence,
        ))

    clauses: list[Clause] = []
    for item in semantic.clauses:
        cid, norm_conf = _resolve_id(registry, "clauses", item.canonical_id, item.original_name)
        terms = registry.recovery_terms("clauses", cid, item.original_name)
        evidence = validator.validate_many(
            item.evidence,
            extractor="semantic",
            object_type="clause",
            object_name=item.original_name,
            report=report,
            recovery_terms=terms,
            prefer_formal_heading=True,
        )
        if not evidence:
            support = validator.find_support(terms, prefer_formal_heading=True)
            if support is not None:
                evidence = [support[0]]
        clauses.append(Clause(
            canonical_id=cid,
            original_name=item.original_name,
            description=None,
            extraction_confidence=item.extraction_confidence,
            normalization_confidence=max(norm_conf, item.normalization_confidence if cid else 0.0),
            evidence=evidence,
            category="CONTRACTUAL_CLAUSE",
            summary=item.summary,
            conditions=item.conditions,
        ))

    path_text = str(document.source_file).casefold()
    first_pages_text = "\n".join(page.clean_text for page in document.pages[:8]).casefold()
    if "synthetic" in path_text:
        origin = DocumentOrigin.SYNTHETIC_VITAGUARD
    elif "data/real" in path_text.replace("\\", "/") or "allianz" in path_text:
        origin = DocumentOrigin.PUBLIC_REAL
    else:
        origin = DocumentOrigin.USER_PROVIDED

    if origin == DocumentOrigin.SYNTHETIC_VITAGUARD:
        document_type = DocumentType.ISSUED_POLICY
    elif "condições gerais" in first_pages_text or "condicoes gerais" in first_pages_text:
        document_type = DocumentType.GENERAL_CONDITIONS
    else:
        document_type = DocumentType.UNKNOWN

    source = SourceDocument(
        document_id=document.document_id,
        source_file=document.source_name,
        sha256=document.source_sha256,
        page_count=document.page_count,
        language="pt-BR",
        document_type=document_type,
        origin=origin,
    )

    policy_number = identification.policy_number.value if identification.policy_number.status == ExtractionStatus.FOUND else None
    policy_id = core.policy_id_hint or policy_number or document.document_id

    if document.stats.multimodal_text_pages and document.stats.native_text_pages:
        extraction_method = ExtractionMethod.HYBRID
    elif document.stats.multimodal_text_pages:
        extraction_method = ExtractionMethod.MULTIMODAL
    else:
        extraction_method = ExtractionMethod.NATIVE_TEXT

    policy = PolicyRecord(
        policy_id=policy_id,
        source_documents=[source],
        identification=identification,
        contractual_terms=contractual_terms,
        policy_limits=policy_limits,
        policy_deductibles=policy_deductibles,
        coverages=coverages,
        extensions=extensions,
        exclusions=exclusions,
        definitions=definitions,
        clauses=clauses,
        extraction=ExtractionMetadata(
            schema_version="0.5B.5",
            extraction_method=extraction_method,
            extractor_model=provider_model,
            warnings=[],
            errors=[],
        ),
    )
    return policy, report

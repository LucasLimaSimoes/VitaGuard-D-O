from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from vitaguard_do.comparison import ComparisonStatus, compare_policies, render_markdown
from vitaguard_do.models.schema import (
    Clause,
    ContractualTerms,
    Coverage,
    Deductible,
    Definition,
    DocumentOrigin,
    DocumentType,
    Evidence,
    Exclusion,
    Extension,
    ExtractedField,
    ExtractionMetadata,
    ExtractionMethod,
    ExtractionStatus,
    Limit,
    NormalizedValue,
    PolicyIdentification,
    PolicyRecord,
    SourceDocument,
    ValueKind,
)


def ef(value=None, status=ExtractionStatus.NOT_FOUND, page=1):
    evidence = []
    if status == ExtractionStatus.FOUND:
        evidence = [Evidence(document_id="doc", page=page, excerpt=str(value))]
    return ExtractedField(status=status, value=value, evidence=evidence)


def money(value: str) -> NormalizedValue:
    return NormalizedValue(
        kind=ValueKind.MONEY,
        numeric_value=Decimal(value),
        currency="BRL",
        raw_text=f"R$ {value}",
    )


def policy(
    policy_id: str,
    insurer: str,
    *,
    geo: str = "Mundial",
    geo_canonical: str = "WORLDWIDE",
    jurisdiction: str = "Brasil",
    jurisdiction_canonical: str = "BR",
    trigger: str = "Reclamações com Notificação",
    trigger_canonical: str = "CLAIMS_MADE_WITH_NOTIFICATION",
    extension: bool = False,
    limit_value: str | None = None,
    definition_text: str = "Ato ou omissão do Segurado.",
) -> PolicyRecord:
    return PolicyRecord(
        policy_id=policy_id,
        source_documents=[SourceDocument(
            document_id=f"{policy_id}-doc",
            source_file=f"{policy_id}.pdf",
            document_type=DocumentType.GENERAL_CONDITIONS,
            origin=DocumentOrigin.PUBLIC_REAL,
        )],
        identification=PolicyIdentification(
            insurer=ef(insurer, ExtractionStatus.FOUND, 1),
            product_name=ef("D&O", ExtractionStatus.FOUND, 1),
            susep_process=ef(f"SUSEP-{policy_id}", ExtractionStatus.FOUND, 1),
            policy_number=ef(),
            insured=ef(),
            policyholder=ef(),
            document_version=ef(),
        ),
        contractual_terms=ContractualTerms(
            policy_period=ef(),
            currency=ef(),
            premium=ef(),
            retroactive_date=ef(),
            extended_reporting_period=ef(),
            geographic_scope=ef(geo, ExtractionStatus.FOUND, 2),
            jurisdiction=ef(jurisdiction, ExtractionStatus.FOUND, 2),
            coverage_trigger=ef(trigger, ExtractionStatus.FOUND, 2),
            geographic_scope_canonical=geo_canonical,
            jurisdiction_canonical=jurisdiction_canonical,
            coverage_trigger_canonical=trigger_canonical,
        ),
        policy_limits=(
            [Limit(canonical_id="aggregate_limit", original_name="Limite Máximo de Garantia", value=money(limit_value))]
            if limit_value is not None else []
        ),
        policy_deductibles=[],
        coverages=[Coverage(canonical_id="side_a", original_name="Side A", evidence=[Evidence(document_id="doc", page=3, excerpt="Side A")])],
        extensions=(
            [Extension(canonical_id="investigation_coverage", original_name="Custos de Investigação", evidence=[Evidence(document_id="doc", page=4, excerpt="Custos de Investigação")])]
            if extension else []
        ),
        exclusions=[Exclusion(canonical_id="fraud_or_dishonesty", original_name="Fraude", evidence=[Evidence(document_id="doc", page=5, excerpt="Fraude")])],
        definitions=[Definition(canonical_term="wrongful_act", original_term="Ato Danoso", definition_text=definition_text, evidence=[Evidence(document_id="doc", page=6, excerpt=definition_text)])],
        clauses=[Clause(canonical_id="allocation", original_name="Alocação", evidence=[Evidence(document_id="doc", page=7, excerpt="Alocação")])],
        extraction=ExtractionMetadata(extraction_method=ExtractionMethod.NATIVE_TEXT),
    )


def by_id(report, field_id: str):
    return next(row for row in report.rows if row.field_id == field_id)


def test_two_policy_canonical_scalar_equivalence():
    a = policy("a", "Seguradora A", geo="qualquer lugar do mundo", jurisdiction="Brasil")
    b = policy("b", "Seguradora B", geo="Worldwide", jurisdiction="Brazil")
    report = compare_policies([a, b])
    assert by_id(report, "geographic_scope").status == ComparisonStatus.EQUAL
    assert by_id(report, "jurisdiction").status == ComparisonStatus.EQUAL
    assert by_id(report, "coverage_trigger").status == ComparisonStatus.EQUAL


def test_only_in_some_is_explicit_and_preserves_evidence():
    a = policy("a", "Seguradora A", extension=True)
    b = policy("b", "Seguradora B", extension=False)
    report = compare_policies([a, b])
    row = by_id(report, "investigation_coverage")
    assert row.status == ComparisonStatus.ONLY_IN_SOME
    assert row.values[0].present is True
    assert row.values[0].evidence[0].page == 4
    assert row.values[1].present is False


def test_numeric_equivalence_uses_decimal_not_string_format():
    a = policy("a", "Seguradora A", limit_value="10000000")
    b = policy("b", "Seguradora B", limit_value="10000000.0")
    report = compare_policies([a, b])
    row = by_id(report, "aggregate_limit")
    assert row.status == ComparisonStatus.EQUAL


def test_definition_text_difference_is_material():
    a = policy("a", "Seguradora A", definition_text="Ato ou omissão do Segurado.")
    b = policy("b", "Seguradora B", definition_text="Ato, erro ou omissão do Segurado.")
    report = compare_policies([a, b])
    assert by_id(report, "wrongful_act").status == ComparisonStatus.DIFFERENT


def test_engine_supports_three_policies_without_a_b_hardcoding():
    report = compare_policies([
        policy("a", "Seguradora A", extension=True),
        policy("b", "Seguradora B", extension=True),
        policy("c", "Seguradora C", extension=False),
    ])
    assert report.summary.policy_count == 3
    assert report.policy_ids == ["a", "b", "c"]
    row = by_id(report, "investigation_coverage")
    assert len(row.values) == 3
    assert row.status == ComparisonStatus.ONLY_IN_SOME


def test_markdown_has_dynamic_policy_columns():
    report = compare_policies([
        policy("a", "Seguradora A"),
        policy("b", "Seguradora B"),
        policy("c", "Seguradora C"),
    ])
    text = render_markdown(report)
    assert "Seguradora A" in text
    assert "Seguradora B" in text
    assert "Seguradora C" in text
    assert "IDENTIFICADO SÓ EM ALGUMAS" in text or "IGUAL" in text

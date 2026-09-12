from __future__ import annotations

from vitaguard_do.comparison import (
    ComparisonStatus,
    compare_policies,
    render_markdown,
    select_key_differences,
)
from vitaguard_do.models.schema import Definition, Evidence
from tests.test_v06_comparison_engine import by_id, policy


def test_historical_contractual_values_get_canonical_fallbacks():
    historical = policy(
        "historical",
        "Seguradora Histórica",
        geo="Mundial",
        geo_canonical=None,
        jurisdiction="Brasil",
        jurisdiction_canonical=None,
        trigger="Reclamações com Notificação",
        trigger_canonical=None,
    )
    current = policy(
        "current",
        "Seguradora Atual",
        geo="Worldwide",
        geo_canonical="WORLDWIDE",
        jurisdiction="Brazil",
        jurisdiction_canonical="BR",
        trigger="Claims-made with notification",
        trigger_canonical="CLAIMS_MADE_WITH_NOTIFICATION",
    )

    report = compare_policies([historical, current])

    assert by_id(report, "geographic_scope").status == ComparisonStatus.EQUAL
    assert by_id(report, "jurisdiction").status == ComparisonStatus.EQUAL
    assert by_id(report, "coverage_trigger").status == ComparisonStatus.EQUAL
    assert by_id(report, "jurisdiction").values[0].canonical_value == "BR"


def test_duplicate_canonical_id_explains_which_policy_and_occurrences_need_review():
    a = policy("a", "Seguradora A")
    b = policy("b", "Seguradora B")
    a.definitions.extend([
        Definition(
            canonical_term="subsidiary",
            original_term="Controlada",
            definition_text="Definição A1",
            evidence=[Evidence(document_id="doc", page=12, excerpt="Controlada")],
        ),
        Definition(
            canonical_term="subsidiary",
            original_term="Subsidiária",
            definition_text="Definição A2",
            evidence=[Evidence(document_id="doc", page=13, excerpt="Subsidiária")],
        ),
    ])
    b.definitions.append(
        Definition(
            canonical_term="subsidiary",
            original_term="Subsidiária",
            definition_text="Definição B",
            evidence=[Evidence(document_id="doc", page=13, excerpt="Subsidiária")],
        )
    )

    report = compare_policies([a, b])
    row = by_id(report, "subsidiary")

    assert row.status == ComparisonStatus.NEEDS_REVIEW
    assert any("Seguradora A" in note and "2 ocorrências" in note for note in row.notes)
    assert any("Controlada" in note and "Subsidiária" in note for note in row.notes)

    markdown = render_markdown(report)
    assert "## Itens para revisão" in markdown
    assert "2 ocorrências" in markdown


def test_only_in_some_rendering_is_cautious_about_legal_absence():
    report = compare_policies([
        policy("a", "Seguradora A", extension=True),
        policy("b", "Seguradora B", extension=False),
    ])
    markdown = render_markdown(report)
    assert "IDENTIFICADO EM 1/2" in markdown
    assert "não comprova ausência jurídica" in markdown


def test_key_differences_exclude_identification_metadata():
    report = compare_policies([
        policy("a", "Seguradora A", extension=True),
        policy("b", "Seguradora B", extension=False),
    ])
    key_rows = select_key_differences(report, limit=20)

    assert key_rows
    assert all(row.section != "identification" for row in key_rows)
    assert any(row.field_id == "investigation_coverage" for row in key_rows)

    markdown = render_markdown(report)
    key_section = markdown.split("## Principais diferenças", 1)[1].split("## identification", 1)[0]
    assert "Processo SUSEP" not in key_section
    assert "Seguradora A" in key_section

from __future__ import annotations

from copy import deepcopy

from vitaguard_do import __version__
from vitaguard_do.comparison import (
    ComparisonStatus,
    HarmonizedPresenceStatus,
    compare_policies,
    load_harmonization_config,
    render_markdown,
)
from vitaguard_do.models.schema import Coverage, Deductible, Evidence, Extension
from tests.test_v06_comparison_engine import money, policy


def test_version_v064():
    assert __version__ == '1.0.0'


def test_harmonization_config_is_explicit_and_auditable():
    config = load_harmonization_config()
    assert config.version == '0.6.4'
    ids = {c.id for c in config.concepts}
    assert {'investigation_protection', 'asset_liberty_protection'} <= ids


def test_financial_deductibles_are_keyed_by_canonical_id_and_scope():
    a = policy('a', 'Seguradora A')
    b = policy('b', 'Seguradora B')
    a.policy_deductibles = [
        Deductible(canonical_id='deductible', original_name='Retencao A', value=money('0'), applies_to=['side_a']),
        Deductible(canonical_id='deductible', original_name='Retencao B', value=money('250000'), applies_to=['side_b']),
        Deductible(canonical_id='deductible', original_name='Retencao C', value=money('500000'), applies_to=['side_c']),
    ]
    report = compare_policies([a, b])
    rows = [r for r in report.rows if r.section == 'policy_deductibles']
    assert len(rows) == 3
    assert {tuple(r.scope_ids) for r in rows} == {('side_a',), ('side_b',), ('side_c',)}
    assert all(r.status == ComparisonStatus.ONLY_IN_SOME for r in rows)
    assert not any(r.status == ComparisonStatus.NEEDS_REVIEW for r in rows)


def test_same_financial_scope_can_still_trigger_review():
    a = policy('a', 'Seguradora A')
    b = policy('b', 'Seguradora B')
    a.policy_deductibles = [
        Deductible(canonical_id='deductible', original_name='Retencao B 1', value=money('250000'), applies_to=['side_b']),
        Deductible(canonical_id='deductible', original_name='Retencao B 2', value=money('300000'), applies_to=['Side B']),
    ]
    report = compare_policies([a, b])
    row = next(r for r in report.rows if r.section == 'policy_deductibles')
    assert row.field_id == 'deductible::scope=side_b'
    assert row.status == ComparisonStatus.NEEDS_REVIEW
    assert any('mesma chave comparativa' in note for note in row.notes)


def test_investigation_family_can_be_present_3_of_3_across_sections():
    a = policy('a', 'Seguradora A', extension=True)
    b = policy('b', 'Seguradora B', extension=True)
    c = policy('c', 'Seguradora C', extension=False)
    c.coverages.append(Coverage(
        canonical_id='investigation_costs',
        original_name='Despesas de Investigacao',
        evidence=[Evidence(document_id='doc', page=8, excerpt='Despesas de Investigacao')],
    ))
    report = compare_policies([a, b, c])
    concept = next(c for c in report.harmonized_concepts if c.comparison_concept_id == 'investigation_protection')
    assert concept.status == HarmonizedPresenceStatus.PRESENT_IN_ALL
    assert concept.presence_fraction == '3/3'
    assert set(concept.present_policy_ids) == {'a', 'b', 'c'}
    exact_coverage = next(r for r in report.rows if r.section == 'coverages' and r.field_id == 'investigation_costs')
    exact_extension = next(r for r in report.rows if r.section == 'extensions' and r.field_id == 'investigation_coverage')
    assert exact_coverage.comparison_concept_id == 'investigation_protection'
    assert exact_extension.comparison_concept_id == 'investigation_protection'


def test_asset_liberty_family_does_not_claim_contractual_equality():
    a = policy('a', 'Seguradora A')
    b = policy('b', 'Seguradora B')
    c = policy('c', 'Seguradora C')
    a.extensions.append(Extension(canonical_id='asset_and_liberty_proceedings', original_name='Processos de Bens e Liberdade'))
    b.extensions.append(Extension(canonical_id='asset_freeze_online_seizure', original_name='Bloqueio e Indisponibilidade de Bens'))
    c.coverages.append(Coverage(canonical_id='asset_and_liberty', original_name='Bens e Liberdade'))
    report = compare_policies([a, b, c])
    concept = next(c for c in report.harmonized_concepts if c.comparison_concept_id == 'asset_liberty_protection')
    assert concept.presence_fraction == '3/3'
    assert concept.status == HarmonizedPresenceStatus.PRESENT_IN_ALL
    assert any('não afirma equivalência contratual' in note for note in concept.notes)
    text = render_markdown(report)
    assert 'Visão harmonizada por família' in text
    assert 'não equivalência contratual' in text


def test_defense_cost_definition_is_not_harmonized_with_coverage():
    a = policy('a', 'Seguradora A')
    b = policy('b', 'Seguradora B')
    a.coverages.append(Coverage(canonical_id='defense_costs', original_name='Custos de Defesa'))
    report = compare_policies([a, b])
    coverage = next(r for r in report.rows if r.section == 'coverages' and r.field_id == 'defense_costs')
    assert coverage.comparison_concept_id is None

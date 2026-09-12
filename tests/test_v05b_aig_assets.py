import json
from pathlib import Path

from vitaguard_do.taxonomy.loader import load_taxonomies

ROOT = Path(__file__).resolve().parents[1]


def test_aig_source_manifest_and_gold():
    sources = json.loads((ROOT / 'data' / 'real' / 'sources.json').read_text(encoding='utf-8'))
    source = sources['aig_do_aiggo_2026']
    assert source['expected_pages'] == 72
    assert source['susep_process'] == '15414.901229/2017-25'
    assert source['expected_sha256'] == '700a08f26ab8fd56244b9519c36879627e9fdfd4149366a0d186176ffc5c52c0'
    assert source['pdf_url'].startswith('https://www.aig.com.br/')
    assert len(source['expected_text_markers']) >= 4
    gold = json.loads((ROOT / 'tests' / 'real_gold' / 'aig_do_aiggo_2026.json').read_text(encoding='utf-8'))
    ids = [f['id'] for f in gold['facts']]
    assert len(ids) == 28
    assert len(ids) == len(set(ids))


def test_aig_taxonomy_aliases():
    registry = load_taxonomies(ROOT / 'vitaguard_do' / 'taxonomy')
    cases = [
        ('coverages','GARANTIA A - Segurados','side_a'),
        ('coverages','GARANTIA B - Reembolso à Sociedade','side_b'),
        ('extensions','Bens e Liberdade','asset_and_liberty_proceedings'),
        ('extensions','Bloqueio e Indisponibilidade de Bens','asset_freeze_online_seizure'),
        ('extensions','Custos de Investigação','investigation_coverage'),
        ('exclusions','Danos Ambientais','pollution'),
        ('definitions','Perda Indenizável','loss'),
        ('clauses','Ordem dos Pagamentos','priority_of_payments'),
    ]
    for category, alias, expected in cases:
        assert registry.resolve(category, alias).id == expected

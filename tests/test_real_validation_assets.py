import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_allianz_source_manifest_is_pinned():
    data = json.loads((ROOT / 'data' / 'real' / 'sources.json').read_text(encoding='utf-8'))
    source = data['allianz_do_2025_12']
    assert source['expected_pages'] == 75
    assert len(source['expected_sha256']) == 64
    assert source['pdf_url'].startswith('https://www.allianz.com.br/')


def test_allianz_real_gold_has_unique_20_facts():
    gold = json.loads((ROOT / 'tests' / 'real_gold' / 'allianz_do_2025_12.json').read_text(encoding='utf-8'))
    ids = [fact['id'] for fact in gold['facts']]
    assert len(ids) == 20
    assert len(ids) == len(set(ids))
    assert any(f['kind'] == 'field_status' for f in gold['facts'])
    assert any(f.get('collection') == 'exclusions' for f in gold['facts'])
    assert any(f.get('collection') == 'definitions' for f in gold['facts'])

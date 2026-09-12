from pathlib import Path

from vitaguard_do import __version__
from vitaguard_do.comparison import ComparisonStatus, compare_policies, render_markdown
from tests.test_v06_comparison_engine import by_id, policy


def test_version_v063():
    assert __version__ == '1.0.0'


def test_three_way_presence_metadata_for_two_of_three():
    report = compare_policies([
        policy('a', 'Seguradora A', extension=True),
        policy('b', 'Seguradora B', extension=True),
        policy('c', 'Seguradora C', extension=False),
    ])
    row = by_id(report, 'investigation_coverage')
    assert row.status == ComparisonStatus.ONLY_IN_SOME
    assert row.present_count == 2
    assert row.policy_count == 3
    assert row.present_policy_ids == ['a', 'b']
    assert row.missing_policy_ids == ['c']
    assert row.presence_fraction == '2/3'


def test_three_way_presence_metadata_for_one_of_three():
    report = compare_policies([
        policy('a', 'Seguradora A', extension=True),
        policy('b', 'Seguradora B', extension=False),
        policy('c', 'Seguradora C', extension=False),
    ])
    row = by_id(report, 'investigation_coverage')
    assert row.present_count == 1
    assert row.presence_fraction == '1/3'


def test_markdown_renders_explicit_x_over_n_presence():
    report = compare_policies([
        policy('a', 'Seguradora A', extension=True),
        policy('b', 'Seguradora B', extension=True),
        policy('c', 'Seguradora C', extension=False),
    ])
    text = render_markdown(report)
    assert 'IDENTIFICADO EM 2/3' in text
    assert 'não comprova ausência jurídica' in text


def test_packaged_executive_plus_structured_file_exists_and_is_not_pdf():
    root = Path(__file__).resolve().parents[1]
    path = root / 'data' / 'demo' / 'structured' / 'vitaguard_do_executive_plus.structured.json'
    assert path.exists()
    assert path.suffix == '.json'

from pathlib import Path

from vitaguard_do import __version__


def test_package_has_no_notebooks():
    root = Path(__file__).resolve().parents[1]
    assert not (root / 'notebooks').exists()


def test_package_version_current():
    assert __version__ == '1.0.0'


def test_local_launcher_points_to_current_validator_and_streamlit():
    root = Path(__file__).resolve().parents[1]
    text = (root / 'run_vitaguard.bat').read_text(encoding='utf-8')
    assert 'validate_v100.py' in text
    assert 'streamlit run streamlit_app.py' in text
    assert 'vitaguard_do_v0_6_' not in text

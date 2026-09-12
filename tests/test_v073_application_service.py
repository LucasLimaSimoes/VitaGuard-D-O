from __future__ import annotations

import ast
from pathlib import Path
import shutil
import subprocess
import sys

from vitaguard_do import __version__
from vitaguard_do.application import DemoDataUnavailableError, VitaGuardApplicationService
from tests.test_v06_comparison_engine import policy

ROOT = Path(__file__).resolve().parents[1]


def _write_direct(path: Path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")


def _fixture_tree(tmp_path: Path):
    root = tmp_path / "vitaguard_do_v0_7_3"
    demo = root / "data" / "demo" / "structured"
    _write_direct(demo / "allianz_do_condicoes_gerais_2025_12.structured.json", policy("allianz", "Allianz", extension=True))
    _write_direct(demo / "aig_do_aiggo.structured.json", policy("aig", "AIG", extension=True))
    _write_direct(demo / "vitaguard_do_executive_plus.structured.json", policy("executive", "VitaGuard", extension=False))
    return root


def test_version_v073():
    assert __version__ == "1.0.0"


def test_application_service_uses_only_current_demo_bundle(tmp_path):
    root = _fixture_tree(tmp_path)
    service = VitaGuardApplicationService(root)
    bundle = service.prepare_demo()
    assert set(bundle.files) == {"allianz", "aig", "executive_plus"}
    assert all(str(root / "data" / "demo" / "structured") in p for p in bundle.files.values())
    assert [x.insurer for x in service.list_demo_policies()] == ["Allianz", "AIG", "VitaGuard"]


def test_application_service_fails_without_bundled_asset_even_if_previous_version_exists(tmp_path):
    root = _fixture_tree(tmp_path)
    missing = root / "data" / "demo" / "structured" / "aig_do_aiggo.structured.json"
    missing.unlink()
    previous = tmp_path / "vitaguard_do_v0_6_4" / "outputs" / "real"
    _write_direct(previous / "aig_do_aiggo.structured.json", policy("old-aig", "Old AIG", extension=True))
    service = VitaGuardApplicationService(root)
    try:
        service.prepare_demo()
    except DemoDataUnavailableError as exc:
        assert "autossuficiente" in str(exc)
        assert "aig" in exc.missing
    else:
        raise AssertionError("DemoDataUnavailableError esperado")


def test_application_service_comparison_supports_three_and_two(tmp_path):
    service = VitaGuardApplicationService(_fixture_tree(tmp_path))
    service.prepare_demo()
    assert service.compare_demo().summary.policy_count == 3
    ids = service.policy_ids()
    assert service.compare_demo(ids[:2]).summary.policy_count == 2


def test_application_service_requires_two_selected_policies(tmp_path):
    service = VitaGuardApplicationService(_fixture_tree(tmp_path))
    service.prepare_demo()
    try:
        service.compare_demo([service.policy_ids()[0]])
    except ValueError as exc:
        assert "pelo menos duas" in str(exc)
    else:
        raise AssertionError("ValueError esperado")


def test_processing_stages_are_frontend_friendly(tmp_path):
    service = VitaGuardApplicationService(_fixture_tree(tmp_path))
    service.prepare_demo()
    stages = service.processing_stages(service.policy_ids()[0])
    assert [s.id for s in stages] == ["received", "text", "structured", "evidence", "ready"]
    assert all(s.completed for s in stages)


def test_streamlit_entrypoint_does_not_import_streamlit_or_pdf_at_module_import():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    ast.parse(source)
    code = r'''
import builtins
import importlib.util
import sys
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "streamlit" or name in {"pymupdf", "fitz"}:
        raise ModuleNotFoundError(f"blocked: {name}")
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
spec = importlib.util.spec_from_file_location("vg_streamlit_app", "streamlit_app.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert callable(module.main)
assert "streamlit" not in sys.modules
print("import-ok")
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "import-ok" in result.stdout


def test_distribution_has_windows_launcher_and_no_notebooks():
    assert (ROOT / "run_vitaguard.bat").is_file()
    assert not (ROOT / "notebooks").exists()
    launcher = (ROOT / "run_vitaguard.bat").read_text(encoding="utf-8")
    assert "streamlit run streamlit_app.py" in launcher
    assert "validate_v100.py" in launcher

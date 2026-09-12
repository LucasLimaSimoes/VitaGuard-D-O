from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _ui_module():
    path = ROOT / "streamlit_app.py"
    spec = importlib.util.spec_from_file_location("vg_ui_v0811_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_duplicate_short_labels_are_disambiguated_by_source_file():
    ui = _ui_module()
    policies = [
        SimpleNamespace(
            policy_id="alpha",
            insurer="VitaGuard Seguros Ficticios S.A.",
            product="Seguro D&O",
            source_file="vitaguard_do_imagem_alpha.png",
        ),
        SimpleNamespace(
            policy_id="beta",
            insurer="VitaGuard Seguros Ficticios S.A.",
            product="Seguro D&O",
            source_file="vitaguard_do_imagem_beta.png",
        ),
    ]
    labels = ui._unique_policy_labels(policies)
    assert labels["alpha"] == "VitaGuard · Imagem Alpha"
    assert labels["beta"] == "VitaGuard · Imagem Beta"
    assert len(set(labels.values())) == 2


def test_source_suffix_is_humanized():
    ui = _ui_module()
    assert ui._source_suffix("vitaguard_do_scan_alpha.pdf") == "Scan Alpha"
    assert ui._source_suffix("apolice_cliente-01.pdf") == "Apolice Cliente 01"


def test_live_ui_does_not_render_stale_bundle_after_upload_change():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    mismatch = source.index("if current_job_id and current_job_id != bundle.job_id:")
    list_policies = source.index("policies = service.list_live_policies(bundle)")
    block = source[mismatch:list_policies]
    assert 'st.session_state.pop("vg_live_selected", None)' in block
    assert "return" in block


def test_live_comparison_errors_are_user_friendly_not_raw_tracebacks():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    anchor = source.index("report = service.compare_live(bundle, selected)")
    block = source[anchor - 200: anchor + 650]
    assert "except (ValueError, KeyError)" in block
    assert 'st.warning(str(exc))' in block
    assert "st.exception" not in block

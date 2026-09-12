from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from vitaguard_do.comparison import ComparisonStatus

ROOT = Path(__file__).resolve().parents[1]


def _ui_module():
    path = ROOT / "streamlit_app.py"
    spec = importlib.util.spec_from_file_location("vg_ui_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_short_policy_labels_are_frontend_friendly():
    ui = _ui_module()
    assert ui._policy_short_label(SimpleNamespace(insurer="Allianz Seguros S.A.", product="Produto D&O")) == "Allianz"
    assert ui._policy_short_label(SimpleNamespace(insurer="AIG Seguros Brasil S.A.", product="D&O")) == "AIG"
    assert ui._policy_short_label(SimpleNamespace(insurer="VitaGuard Seguros Ficticios S.A.", product="VitaGuard D&O Executive Plus")) == "VitaGuard Executive Plus"


def test_not_found_is_presented_in_portuguese_not_internal_enum():
    ui = _ui_module()
    value = SimpleNamespace(
        present=False,
        extraction_status=SimpleNamespace(value="NOT_FOUND"),
        source_name=None,
        value=None,
    )
    assert ui._value_text(value) == "Não identificado"
    assert "NOT_FOUND" not in ui._value_text(value)


def test_partial_presence_is_humanized():
    ui = _ui_module()
    row = SimpleNamespace(
        status=ComparisonStatus.ONLY_IN_SOME,
        present_count=2,
        policy_count=3,
        presence_fraction="2/3",
        comparison_concept_id=None,
    )
    text = ui._result_text(row)
    assert "Presente em 2 de 3" in text
    assert "identificadas" not in text


def test_partial_presence_can_show_harmonized_family_context():
    ui = _ui_module()
    row = SimpleNamespace(
        status=ComparisonStatus.ONLY_IN_SOME,
        present_count=1,
        policy_count=3,
        presence_fraction="1/3",
        comparison_concept_id="investigation_protection",
    )
    text = ui._result_text(row, "3/3")
    assert "Presente em 1 de 3" in text
    assert "família 3/3" in text


def test_structured_period_is_human_readable():
    ui = _ui_module()
    assert ui._format_structured_value({"start": "2026-02-01", "end": "2027-02-01"}) == "01/02/2026 a 01/02/2027"
    assert ui._format_structured_value(date(2020, 2, 1)) == "01/02/2020"


def test_financial_item_displays_value_not_internal_original_name():
    ui = _ui_module()
    value = SimpleNamespace(
        present=True,
        extraction_status=SimpleNamespace(value="FOUND"),
        source_name="Limite agregado",
        value={
            "original_name": "Limite agregado",
            "value": {"kind": "MONEY", "raw_text": "R$ 25.000.000,00", "numeric_value": "25000000"},
        },
    )
    assert ui._value_text(value) == "R$ 25.000.000,00"


def test_compact_text_preserves_short_and_truncates_long():
    ui = _ui_module()
    assert ui._compact_text("Texto curto", 20) == "Texto curto"
    result = ui._compact_text("a" * 100, 20)
    assert len(result) == 20
    assert result.endswith("…")


def test_final_demo_polish_is_present():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert '"Analisar documentos"' in source
    assert "Novos PDFs — v0.8" not in source
    assert '[data-testid="stToolbar"]' in source
    assert "Iguais" in source
    assert 'with st.expander("Abrir matriz técnica completa", expanded=False)' in source
    assert "família X/N" in source

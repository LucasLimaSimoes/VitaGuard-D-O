from __future__ import annotations

import json
from pathlib import Path

import pytest

from vitaguard_do.comparison.io import load_policy_record
from tests.test_v06_comparison_engine import policy


def test_loader_accepts_bare_policy_record(tmp_path: Path):
    expected = policy("direct", "Seguradora Direta")
    path = tmp_path / "direct.json"
    path.write_text(expected.model_dump_json(indent=2), encoding="utf-8")

    loaded = load_policy_record(path)

    assert loaded.policy_id == "direct"
    assert loaded.identification.insurer.value == "Seguradora Direta"


def test_loader_accepts_structured_extraction_run_envelope(tmp_path: Path):
    expected = policy("wrapped", "Seguradora Envelope")
    envelope = {
        "project_version": "0.5A.3",
        "document_id": "doc-123",
        "source_name": "arquivo.pdf",
        "provider": "gemini",
        "model": "gemini-test",
        "selected_chunks": {},
        "core": {},
        "risk": {},
        "semantic": {},
        "evidence_report": {},
        "policy_json": expected.model_dump(mode="json"),
        "warnings": [],
    }
    path = tmp_path / "wrapped.structured.json"
    path.write_text(json.dumps(envelope, ensure_ascii=False, default=str), encoding="utf-8")

    loaded = load_policy_record(path)

    assert loaded.policy_id == "wrapped"
    assert loaded.identification.insurer.value == "Seguradora Envelope"


def test_loader_rejects_unknown_wrapper_with_clear_message(tmp_path: Path):
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps({"project_version": "x", "something_else": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="policy_json"):
        load_policy_record(path)

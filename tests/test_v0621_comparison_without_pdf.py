from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from vitaguard_do.contractual_normalization import canonicalize_contractual_field


ROOT = Path(__file__).resolve().parents[1]


def test_shared_contractual_normalization():
    assert canonicalize_contractual_field(
        "contractual_terms.jurisdiction", "Brasil"
    ) == "BR"


def test_comparison_imports_when_pdf_backends_are_unavailable():
    code = r"""
import importlib.abc
import sys

class BlockPdf(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"pymupdf", "fitz"} or fullname.startswith("pymupdf."):
            raise ModuleNotFoundError(f"blocked for comparison-only test: {fullname}")
        return None

sys.meta_path.insert(0, BlockPdf())

from vitaguard_do.comparison.io import load_policy_record
from vitaguard_do.comparison.engine import compare_portfolio

assert "vitaguard_do.ingestion.pdf" not in sys.modules
assert "pymupdf" not in sys.modules
assert "fitz" not in sys.modules
print("comparison-import-ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "comparison-import-ok" in result.stdout


def test_engine_does_not_import_extraction_normalization():
    text = (ROOT / "vitaguard_do" / "comparison" / "engine.py").read_text(encoding="utf-8")
    assert "vitaguard_do.contractual_normalization" in text
    assert "vitaguard_do.extraction.normalization" not in text

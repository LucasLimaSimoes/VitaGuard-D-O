from pathlib import Path

import pymupdf as fitz
import pytest

from vitaguard_do import real_sources


def _make_pdf(path: Path, pages: int = 2) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Test page {i + 1}")
    doc.save(path)
    doc.close()


def test_install_local_real_source_validates_before_copy(monkeypatch, tmp_path):
    src = tmp_path / "source.pdf"
    _make_pdf(src, 2)
    target = tmp_path / "cached.pdf"

    sha = real_sources.sha256_file(src)
    meta = {
        "display_name": "Test",
        "official_page_url": "https://example.test/page",
        "pdf_url": "https://example.test/file.pdf",
        "target_file": target.name,
        "expected_sha256": sha,
        "expected_pages": 2,
    }

    monkeypatch.setattr(real_sources, "load_real_sources", lambda: {"test": meta})
    monkeypatch.setattr(real_sources, "ROOT", tmp_path)

    installed = real_sources.install_local_real_source("test", src, strict=True)
    assert installed.exists()
    assert installed == tmp_path / "data" / "real" / target.name
    assert real_sources.sha256_file(installed) == sha


def test_install_local_real_source_rejects_wrong_pdf(monkeypatch, tmp_path):
    src = tmp_path / "wrong.pdf"
    _make_pdf(src, 1)
    meta = {
        "display_name": "Test",
        "official_page_url": "https://example.test/page",
        "pdf_url": "https://example.test/file.pdf",
        "target_file": "cached.pdf",
        "expected_sha256": "0" * 64,
        "expected_pages": 2,
    }
    monkeypatch.setattr(real_sources, "load_real_sources", lambda: {"test": meta})
    monkeypatch.setattr(real_sources, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="SHA-256"):
        real_sources.install_local_real_source("test", src, strict=True)

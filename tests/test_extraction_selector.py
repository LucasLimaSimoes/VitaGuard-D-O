from pathlib import Path

from vitaguard_do.extraction.selector import select_chunks
from vitaguard_do.ingestion.pdf import ingest_pdf


ROOT = Path(__file__).resolve().parents[1]


def test_selector_routes_synthetic_pages_reasonably():
    doc = ingest_pdf(ROOT / "data" / "synthetic" / "vitaguard_do_essencial.pdf")
    core_pages = {c.page_number for c in select_chunks(doc, "core")}
    risk_pages = {c.page_number for c in select_chunks(doc, "risk")}
    semantic_pages = {c.page_number for c in select_chunks(doc, "semantic")}

    assert 1 in core_pages
    assert 3 in risk_pages
    assert 5 in risk_pages
    assert 2 in semantic_pages
    assert 6 in semantic_pages

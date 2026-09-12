from pathlib import Path

from vitaguard_do.ingestion import IngestedDocument, ingest_pdf, save_ingested_document


ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_pdfs_ingest_with_traceable_chunks(tmp_path):
    pdfs = sorted((ROOT / "data" / "synthetic").glob("*.pdf"))
    assert len(pdfs) == 2

    for pdf in pdfs:
        doc = ingest_pdf(pdf)
        assert doc.page_count == 6
        assert doc.stats.native_text_pages == 6
        assert doc.stats.low_text_pages == 0
        assert doc.stats.empty_pages == 0
        assert doc.stats.chunk_count >= 6
        assert len(doc.source_sha256) == 64

        for chunk in doc.chunks:
            page = doc.page(chunk.page_number)
            assert page.clean_text[chunk.char_start:chunk.char_end] == chunk.text
            assert chunk.document_id == doc.document_id

        output = save_ingested_document(doc, tmp_path / f"{pdf.stem}.json")
        loaded = IngestedDocument.from_json_file(output)
        assert loaded.source_sha256 == doc.source_sha256
        assert loaded.stats == doc.stats


def test_document_id_is_deterministic_for_same_file():
    pdf = ROOT / "data" / "synthetic" / "vitaguard_do_essencial.pdf"
    a = ingest_pdf(pdf)
    b = ingest_pdf(pdf)
    assert a.document_id == b.document_id

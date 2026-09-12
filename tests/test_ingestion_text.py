from vitaguard_do.ingestion import IngestionConfig
from vitaguard_do.ingestion.text import (
    chunk_page_text,
    detect_repeated_marginal_lines,
    normalize_extracted_text,
    remove_marginal_lines,
)


def test_normalize_text_preserves_paragraph_breaks():
    raw = "  A   B  \r\n\r\n  C\tD  \n\n\nE "
    assert normalize_extracted_text(raw) == "A B\n\nC D\n\nE"


def test_repeated_header_and_page_number_are_detected_and_removed():
    cfg = IngestionConfig(repeated_line_min_pages=3, repeated_line_min_ratio=0.6)
    pages = [
        f"VitaGuard D&O\nConteudo exclusivo da pagina {i}.\nMais texto.\nPagina {i}"
        for i in range(1, 6)
    ]
    keys = detect_repeated_marginal_lines(pages, cfg)
    cleaned, removed = remove_marginal_lines(pages[0], keys, cfg)
    assert "VitaGuard D&O" in removed
    assert "Pagina 1" in removed
    assert "Conteudo exclusivo" in cleaned


def test_chunk_offsets_are_exact_and_size_is_bounded():
    cfg = IngestionConfig(max_chunk_chars=600, overlap_chars=100)
    text = " ".join(f"palavra{i}" for i in range(400))
    chunks = chunk_page_text(document_id="doc", page_number=2, text=text, config=cfg)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text == text[chunk.char_start:chunk.char_end]
        assert len(chunk.text) <= cfg.max_chunk_chars
        assert chunk.page_number == 2

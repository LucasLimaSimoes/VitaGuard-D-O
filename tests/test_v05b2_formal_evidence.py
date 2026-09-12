from vitaguard_do.extraction.evidence import EvidenceValidator
from vitaguard_do.ingestion.models import (
    IngestedDocument, IngestedPage, IngestionConfig, IngestionStats, PageTextStatus, TextChunk,
)


def _doc() -> IngestedDocument:
    texts = {
        6: "Custos de Investigação, cobertos via Extensão de Cobertura para Custos de Investigação, se contratada.",
        19: "5.7 Custos de Investigação\nContratada esta extensão de cobertura, a Seguradora pagará os custos elegíveis.",
    }
    pages=[]; chunks=[]
    for p in range(1, 30):
        text=texts.get(p, f"pagina {p} sem termo relevante")
        pages.append(IngestedPage(page_number=p,status=PageTextStatus.NATIVE_TEXT,raw_text=text,clean_text=text,raw_char_count=len(text),clean_char_count=len(text),sha256=f"p{p}"))
        chunks.append(TextChunk(chunk_id=f"mock:p{p}:c0",document_id="mock",page_number=p,chunk_index_on_page=0,char_start=0,char_end=len(text),text=text,sha256=f"c{p}"))
    return IngestedDocument(document_id="mock",source_file="mock.pdf",source_name="mock.pdf",source_sha256="mock",page_count=29,config=IngestionConfig(),pages=pages,chunks=chunks,stats=IngestionStats(page_count=29,native_text_pages=29,low_text_pages=0,empty_pages=0,total_raw_chars=sum(len(p.raw_text) for p in pages),total_clean_chars=sum(len(p.clean_text) for p in pages),chunk_count=29,repeated_marginal_lines_detected=0))


def test_formal_heading_outweighs_earlier_incidental_mention():
    validator = EvidenceValidator(_doc())
    hit = validator.find_support(
        ["Extensão de Cobertura para Custos de Investigação", "Custos de Investigação"],
        prefer_formal_heading=True,
    )
    assert hit is not None
    evidence, matched = hit
    assert evidence.page == 19
    assert "5.7 Custos de Investigação" in evidence.excerpt

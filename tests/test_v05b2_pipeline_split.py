from pathlib import Path

from vitaguard_do.extraction.pipeline import StructuredExtractionPipeline
from vitaguard_do.ingestion.models import (
    IngestedDocument, IngestedPage, IngestionConfig, IngestionStats, PageTextStatus, TextChunk,
)
from vitaguard_do.taxonomy.loader import load_taxonomies


class FakeProvider:
    provider_name = "fake"
    model = "fake-model"
    model_summary = "fake-model"

    def __init__(self):
        self.schemas = []

    def generate_structured(self, prompt, schema):
        self.schemas.append(schema.__name__)
        return schema()


def _doc():
    pages=[]; chunks=[]
    for p in range(1, 30):
        if p == 9:
            text = "2.26. Perda Indenizável\nIndenização e custas cobertas."
        elif p == 12:
            text = "2.38. Segurado\nQualquer pessoa física que seja Diretor ou Empregado."
        elif p == 13:
            text = "2.42. Subsidiária\nUma entidade controlada pelo Tomador."
        elif p == 20:
            text = "9.18. Ordem dos Pagamentos\nA Seguradora observará a ordem prevista."
        else:
            text = f"Página contratual {p}."
        pages.append(IngestedPage(page_number=p,status=PageTextStatus.NATIVE_TEXT,raw_text=text,clean_text=text,raw_char_count=len(text),clean_char_count=len(text),sha256=f"p{p}"))
        chunks.append(TextChunk(chunk_id=f"mock:p{p}:c0",document_id="mock",page_number=p,chunk_index_on_page=0,char_start=0,char_end=len(text),text=text,sha256=f"c{p}"))
    return IngestedDocument(document_id="mock",source_file="data/real/mock.pdf",source_name="mock.pdf",source_sha256="mock",page_count=29,config=IngestionConfig(),pages=pages,chunks=chunks,stats=IngestionStats(page_count=29,native_text_pages=29,low_text_pages=0,empty_pages=0,total_raw_chars=sum(len(p.raw_text) for p in pages),total_clean_chars=sum(len(p.clean_text) for p in pages),chunk_count=29,repeated_marginal_lines_detected=0))


def test_long_document_pipeline_splits_risk_and_semantic_calls(tmp_path: Path):
    provider = FakeProvider()
    pipe = StructuredExtractionPipeline(provider, registry=load_taxonomies(), output_dir=tmp_path)
    policy, run = pipe.extract(_doc(), use_cache=False, force=True)
    assert provider.schemas == ["CoreExtraction", "CoveragesExtensionsExtraction", "ExclusionsExtraction", "DefinitionsExtraction", "ClausesExtraction"]
    assert "risk_coverages_extensions" in run.selected_chunks
    assert "risk_exclusions" in run.selected_chunks
    assert "semantic_definitions" in run.selected_chunks
    assert "semantic_clauses" in run.selected_chunks

from vitaguard_do.extraction.models import ClausesExtraction, DefinitionsExtraction
from vitaguard_do.extraction.selector import detect_semantic_candidates
from vitaguard_do.ingestion.models import TextChunk
from vitaguard_do.taxonomy.loader import load_taxonomies


def _chunk(text: str, page: int) -> TextChunk:
    return TextChunk(chunk_id=f"mock:p{page}:c0",document_id="mock",page_number=page,chunk_index_on_page=0,char_start=0,char_end=len(text),text=text,sha256="mock")


def test_split_semantic_schemas_are_objects():
    assert DefinitionsExtraction.model_json_schema()["type"] == "object"
    assert ClausesExtraction.model_json_schema()["type"] == "object"


def test_aig_style_numbered_definition_candidates_are_detected():
    registry = load_taxonomies()
    chunks = [
        _chunk("2.26. Perda Indenizável\nIndenização e custas...", 9),
        _chunk("2.38. Segurado\nQualquer pessoa física que seja...", 12),
        _chunk("2.42. Subsidiária\nUma entidade na qual o Tomador...", 13),
    ]
    found = detect_semantic_candidates(chunks, "definitions", registry=registry)
    assert {"loss", "insured_person", "subsidiary"}.issubset(found)


def test_aig_style_numbered_clause_candidate_is_detected():
    registry = load_taxonomies()
    chunks = [_chunk("9.18. Ordem dos Pagamentos\nNo caso de Custos de Defesa...", 51)]
    found = detect_semantic_candidates(chunks, "clauses", registry=registry)
    assert "priority_of_payments" in found

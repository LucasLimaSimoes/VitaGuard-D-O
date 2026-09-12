from vitaguard_do.extraction.selector import _alias_score, _core_identity_score
from vitaguard_do.ingestion.models import TextChunk


def _chunk(text: str, page: int = 1) -> TextChunk:
    return TextChunk(
        chunk_id=f"mock:p{page}:c0",
        document_id="mock",
        page_number=page,
        chunk_index_on_page=0,
        char_start=0,
        char_end=len(text),
        text=text,
        sha256="mock",
    )


def test_numbered_definition_heading_outranks_incidental_mention():
    heading = _chunk(
        "1.5. Ato Danoso ou Fato Gerador\nQualquer acontecimento que produza danos.",
        3,
    )
    incidental = _chunk(
        "Uma Reclamação decorrente de um Ato Danoso pode estar sujeita a esta cláusula.",
        20,
    )
    heading_score = _alias_score(
        heading,
        ("Ato Danoso", "Ato Danoso ou Fato Gerador"),
        mode="definition",
    )
    incidental_score = _alias_score(
        incidental,
        ("Ato Danoso", "Ato Danoso ou Fato Gerador"),
        mode="definition",
    )
    assert heading_score > incidental_score + 100


def test_numbered_segurado_and_subsidiaria_headings_are_strong_definition_hits():
    segurado = _chunk("2.38. Segurado\nQualquer pessoa física que seja...", 12)
    subsidiaria = _chunk("2.42. Subsidiária\nUma entidade na qual o Tomador...", 13)
    assert _alias_score(segurado, ("Segurado",), mode="definition") >= 200
    assert _alias_score(subsidiaria, ("Subsidiária",), mode="definition") >= 200


def test_formal_seguradora_definition_is_a_core_identity_anchor():
    carrier = _chunk(
        "2.40. Seguradora\nRefere-se à AIG Seguros Brasil S.A.",
        13,
    )
    assert _core_identity_score(carrier) >= 500

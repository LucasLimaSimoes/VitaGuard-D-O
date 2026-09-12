from __future__ import annotations

from vitaguard_do.extraction.evidence import EvidenceValidator
from vitaguard_do.extraction.selector import (
    _alias_score,
    detect_risk_candidates,
    select_risk_subchunks,
    select_semantic_subchunks,
    selected_pages,
)
from vitaguard_do.ingestion.models import (
    IngestedDocument,
    IngestedPage,
    IngestionConfig,
    IngestionStats,
    PageTextStatus,
    TextChunk,
)
from vitaguard_do.taxonomy.loader import load_taxonomies


def _chunk(text: str, page: int) -> TextChunk:
    return TextChunk(
        chunk_id=f"mock:p{page}:c0",
        document_id="mock",
        page_number=page,
        chunk_index_on_page=0,
        char_start=0,
        char_end=len(text),
        text=text,
        sha256=f"c{page}",
    )


def _doc(overrides: dict[int, str], page_count: int = 30) -> IngestedDocument:
    pages = []
    chunks = []
    for page_number in range(1, page_count + 1):
        text = overrides.get(page_number, f"Pagina contratual {page_number} sem conceito relevante.")
        pages.append(IngestedPage(
            page_number=page_number,
            status=PageTextStatus.NATIVE_TEXT,
            raw_text=text,
            clean_text=text,
            raw_char_count=len(text),
            clean_char_count=len(text),
            sha256=f"p{page_number}",
        ))
        chunks.append(_chunk(text, page_number))
    return IngestedDocument(
        document_id="mock",
        source_file="data/real/mock.pdf",
        source_name="mock.pdf",
        source_sha256="mock",
        page_count=page_count,
        config=IngestionConfig(),
        pages=pages,
        chunks=chunks,
        stats=IngestionStats(
            page_count=page_count,
            native_text_pages=page_count,
            low_text_pages=0,
            empty_pages=0,
            total_raw_chars=sum(len(p.raw_text) for p in pages),
            total_clean_chars=sum(len(p.clean_text) for p in pages),
            chunk_count=page_count,
            repeated_marginal_lines_detected=0,
        ),
    )


def test_definition_boundary_does_not_confuse_segurado_with_seguradora():
    insured = _alias_score(_chunk("2.38. Segurado\nPessoa fisica que exerça cargo de administrador.", 12), ("Segurado",), mode="definition")
    insurer = _alias_score(_chunk("2.40. Seguradora\nAIG Seguros Brasil S.A.", 13), ("Segurado",), mode="definition")
    assert insured > 400
    assert insurer == 0


def test_definition_selector_reserves_aig_style_segurado_page():
    registry = load_taxonomies()
    doc = _doc({
        12: "2.38. Segurado\nPessoa fisica que exerça cargo de administrador.",
        13: "2.40. Seguradora\nAIG Seguros Brasil S.A.\n2.42. Subsidiária\nSociedade controlada.",
    })
    selected = select_semantic_subchunks(doc, "definitions", registry=registry)
    assert 12 in selected_pages(selected)


def test_risk_exclusion_split_reserves_dense_formal_headings():
    registry = load_taxonomies()
    doc = _doc({
        28: "7.6. Danos Corporais e Materiais\nTexto da exclusao.\n7.7. Danos Ambientais\nTexto da exclusao.",
        29: "7.8. Reclamações e Circunstâncias Anteriores\nTexto da exclusao.",
    })
    selected = select_risk_subchunks(doc, "exclusions", registry=registry)
    pages = selected_pages(selected)
    assert 28 in pages and 29 in pages
    candidates = detect_risk_candidates(selected, "exclusions", registry=registry)
    assert "exclusions:bodily_injury_property_damage" in candidates
    assert "exclusions:prior_claims_or_circumstances" in candidates


def test_recovery_terms_keep_specific_shorter_formal_investigation_heading():
    registry = load_taxonomies()
    terms = registry.recovery_terms(
        "extensions",
        "investigation_coverage",
        "Extensão de Cobertura para Custos de Investigação",
    )
    normalized = {t.casefold() for t in terms}
    assert "custos de investigação" in normalized


def test_formal_recovery_prefers_numbered_section_over_plain_cross_reference():
    doc = _doc({
        6: "Extensão de Cobertura para Custos de Investigação\nVeja a cobertura descrita adiante.",
        19: "5.7 Custos de Investigação\nContratada esta extensão, a Seguradora pagará os custos elegíveis.",
    })
    validator = EvidenceValidator(doc)
    registry = load_taxonomies()
    terms = registry.recovery_terms(
        "extensions",
        "investigation_coverage",
        "Extensão de Cobertura para Custos de Investigação",
    )
    hit = validator.find_support(terms, prefer_formal_heading=True)
    assert hit is not None
    evidence, _ = hit
    assert evidence.page == 19
    assert "5.7 Custos de Investigação" in evidence.excerpt


def test_formal_recovery_accepts_longer_cooperation_heading():
    doc = _doc({
        50: "9.12 Cooperação do Segurado\nO Segurado deverá cooperar com a Seguradora.",
    }, page_count=55)
    validator = EvidenceValidator(doc)
    registry = load_taxonomies()
    terms = registry.recovery_terms("clauses", "cooperation", "Cooperação")
    hit = validator.find_support(terms, preferred_page=50, prefer_formal_heading=True)
    assert hit is not None
    evidence, _ = hit
    assert evidence.page == 50
    assert "Cooperação do Segurado" in evidence.excerpt

from pathlib import Path

from vitaguard_do.evaluation.real_gold import evaluate_real_gold
from vitaguard_do.extraction.deterministic import (
    canonicalize_document_version,
    find_susep_process,
)
from vitaguard_do.extraction.evidence import EvidenceValidator
from vitaguard_do.extraction.models import EvidenceRef, EvidenceValidationReport
from vitaguard_do.ingestion.pdf import ingest_pdf
from vitaguard_do.taxonomy.loader import load_taxonomies


ROOT = Path(__file__).resolve().parents[1]


def test_document_version_normalization_equivalence():
    assert canonicalize_document_version("dezembro/2025") == "2025-12"
    assert canonicalize_document_version("2025-12") == "2025-12"
    assert canonicalize_document_version("Março/2024") == "2024-03"


def test_allianz_taxonomy_gaps_from_v05a1_are_now_resolved():
    registry = load_taxonomies(ROOT / "vitaguard_do" / "taxonomy")
    cases = [
        ("definitions", "GASTOS COM DEFESA", "defense_costs"),
        ("exclusions", "CLÁUSULA DE EXCLUSÃO DE ADMINISTRADOR DE PREVIDÊNCIA COMPLEMENTAR", "supplementary_pension_administrator"),
        ("exclusions", "CLÁUSULA DE EXCLUSÃO DE LITÍGIO ANTERIOR E PENDENTE", "prior_and_pending_litigation"),
        ("exclusions", "CLÁUSULA DE EXCLUSÃO DE OFERTA DE TÍTULOS MOBILIÁRIOS", "securities_offering"),
        ("extensions", "COBERTURA PARA INDISPONIBILIDADE DE BENS POR BLOQUEIO E PENHORA ONLINE", "asset_freeze_online_seizure"),
        ("extensions", "COBERTURA PARA INVESTIGAÇÃO", "investigation_coverage"),
        ("extensions", "COBERTURA PARA PROCESSOS DE BENS E LIBERDADE", "asset_and_liberty_proceedings"),
    ]
    for category, text, expected in cases:
        item = registry.resolve(category, text)
        assert item is not None, (category, text)
        assert item.id == expected


def test_evidence_validator_can_recover_invalid_claim_from_same_page():
    doc = ingest_pdf(ROOT / "data" / "synthetic" / "vitaguard_do_essencial.pdf")
    chunk = next(c for c in doc.chunks if c.page_number == 1)
    validator = EvidenceValidator(doc)
    report = EvidenceValidationReport()

    # Deliberately invalid excerpt. The deterministic recovery term exists on
    # the same page and must become verbatim source evidence.
    refs = [EvidenceRef(
        chunk_id=chunk.chunk_id,
        page_number=1,
        excerpt="Trecho que nao existe no documento",
    )]
    evidence = validator.validate_many(
        refs,
        extractor="test",
        object_type="financial",
        object_name="LMG",
        report=report,
        recovery_terms=["Limite Maximo de Garantia"],
    )

    assert len(evidence) == 1
    assert evidence[0].page == 1
    assert "Limite Maximo de Garantia" in evidence[0].excerpt
    assert report.valid_claims == 1
    assert report.invalid_claims == 0
    assert report.recovered_claims == 1
    assert len(report.recoveries) == 1


def test_susep_fallback_reads_raw_footer_even_when_clean_text_removed():
    from vitaguard_do.ingestion.models import (
        IngestedDocument, IngestedPage, IngestionConfig, IngestionStats, PageTextStatus,
    )

    raw = "Cabecalho\nAllianz Seguros S.A. Pagina 2 de 75\nProcesso SUSEP nº 15414.901113/2017-96"
    clean = "Cabecalho"
    page = IngestedPage(
        page_number=1,
        status=PageTextStatus.NATIVE_TEXT,
        raw_text=raw,
        clean_text=clean,
        raw_char_count=len(raw),
        clean_char_count=len(clean),
        sha256="0" * 64,
    )
    doc = IngestedDocument(
        document_id="test-doc",
        source_file="test.pdf",
        source_name="test.pdf",
        source_sha256="1" * 64,
        page_count=1,
        config=IngestionConfig(),
        pages=[page],
        chunks=[],
        stats=IngestionStats(
            page_count=1,
            native_text_pages=1,
            low_text_pages=0,
            empty_pages=0,
            total_raw_chars=len(raw),
            total_clean_chars=len(clean),
            chunk_count=0,
            repeated_marginal_lines_detected=1,
        ),
    )
    result = find_susep_process(doc)
    assert result is not None
    assert result.value == "15414.901113/2017-96"
    assert result.evidence.page == 1
    assert result.evidence.chunk_id is None

from pathlib import Path

from vitaguard_do.extraction.evidence import EvidenceValidator
from vitaguard_do.extraction.models import EvidenceRef, EvidenceValidationReport
from vitaguard_do.ingestion.pdf import ingest_pdf


ROOT = Path(__file__).resolve().parents[1]


def test_evidence_validator_accepts_verbatim_excerpt_and_rejects_hallucination():
    doc = ingest_pdf(ROOT / "data" / "synthetic" / "vitaguard_do_essencial.pdf")
    chunk = next(c for c in doc.chunks if c.page_number == 1)
    validator = EvidenceValidator(doc)
    report = EvidenceValidationReport()

    valid = validator.validate_ref(
        EvidenceRef(
            chunk_id=chunk.chunk_id,
            page_number=1,
            excerpt="Limite Maximo de Garantia",
            section="Especificacao",
        ),
        extractor="test",
        object_type="field",
        object_name="limit",
        report=report,
    )
    invalid = validator.validate_ref(
        EvidenceRef(
            chunk_id=chunk.chunk_id,
            page_number=1,
            excerpt="Este texto nunca apareceu na apolice",
        ),
        extractor="test",
        object_type="field",
        object_name="fake",
        report=report,
    )

    assert valid is not None
    assert invalid is None
    assert report.total_claims == 2
    assert report.valid_claims == 1
    assert report.invalid_claims == 1


def test_evidence_validator_repairs_tiny_transcription_error():
    document = ingest_pdf(ROOT / "data" / "synthetic" / "vitaguard_do_essencial.pdf")
    chunk = next(c for c in document.chunks if c.page_number == 1)
    validator = EvidenceValidator(document)
    report = EvidenceValidationReport()

    ref = EvidenceRef(
        chunk_id=chunk.chunk_id,
        page_number=chunk.page_number,
        excerpt="Limite Maximo de Garantia R$ 10.000.00O,00",
    )
    evidence = validator.validate_ref(
        ref,
        extractor="test",
        object_type="financial",
        object_name="LMG",
        report=report,
    )

    assert evidence is not None
    assert report.valid_claims == 1
    assert report.invalid_claims == 0
    assert report.repaired_claims == 1
    assert evidence.excerpt in document.chunks[0].text

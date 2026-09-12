from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from vitaguard_do.ingestion.models import PageTextOrigin
from vitaguard_do.ingestion.multimodal import ingest_document


def _make_png(path: Path, text: str = "APOLICE D&O TESTE") -> None:
    doc = fitz.open()
    page = doc.new_page(width=800, height=1100)
    page.insert_text((72, 100), text, fontsize=18)
    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
    path.write_bytes(pix.tobytes("png"))
    doc.close()


def _make_blank_scanned_pdf(path: Path, page_count: int = 2) -> None:
    doc = fitz.open()
    for _ in range(page_count):
        doc.new_page(width=600, height=800)
    doc.save(path)
    doc.close()


class FakeMultimodal:
    model = "fake-multimodal"

    def __init__(self):
        self.calls: list[tuple[str, int | None]] = []

    def transcribe_image(self, image_bytes, mime_type, *, source_name="", page_number=None):
        assert image_bytes
        assert mime_type.startswith("image/")
        self.calls.append((source_name, page_number))
        return (
            "SEGURADORA TESTE S.A.\n"
            "SEGURO D&O\n"
            f"PAGINA {page_number or 1}\n"
            "COBERTURA A - SEGURADOS\n"
            "LIMITE: R$ 1.000.000,00"
        )


def test_image_document_uses_multimodal_and_preserves_page_evidence(tmp_path):
    image = tmp_path / "apolice.png"
    _make_png(image)
    fake = FakeMultimodal()

    doc = ingest_document(image, extractor=fake, cache_dir=tmp_path / "ocr")

    assert doc.source_mime_type == "image/png"
    assert doc.page_count == 1
    assert doc.stats.native_text_pages == 0
    assert doc.stats.multimodal_text_pages == 1
    assert doc.pages[0].text_origin == PageTextOrigin.GEMINI_MULTIMODAL
    assert doc.chunks and all(c.page_number == 1 for c in doc.chunks)
    assert len(fake.calls) == 1


def test_scanned_pdf_falls_back_page_by_page_and_caches_transcription(tmp_path):
    pdf = tmp_path / "scan.pdf"
    _make_blank_scanned_pdf(pdf, 2)
    cache = tmp_path / "ocr"
    fake = FakeMultimodal()

    doc1 = ingest_document(pdf, extractor=fake, cache_dir=cache)
    assert doc1.page_count == 2
    assert doc1.stats.native_text_pages == 0
    assert doc1.stats.multimodal_text_pages == 2
    assert len(fake.calls) == 2
    assert all(p.text_origin == PageTextOrigin.GEMINI_MULTIMODAL for p in doc1.pages)

    fake2 = FakeMultimodal()
    doc2 = ingest_document(pdf, extractor=fake2, cache_dir=cache)
    assert doc2.stats.multimodal_text_pages == 2
    assert fake2.calls == []


def test_native_pdf_skips_multimodal_when_text_is_sufficient(tmp_path):
    pdf = tmp_path / "native.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(50, 50, 550, 700),
        ("CONDIÇÕES GERAIS D&O. COBERTURA A. " * 20),
        fontsize=12,
    )
    doc.save(pdf)
    doc.close()

    fake = FakeMultimodal()
    ingested = ingest_document(pdf, extractor=fake, cache_dir=tmp_path / "ocr")
    assert ingested.stats.native_text_pages == 1
    assert ingested.stats.multimodal_text_pages == 0
    assert fake.calls == []


def test_live_application_accepts_two_images_end_to_end_with_fakes(tmp_path):
    from types import SimpleNamespace

    from vitaguard_do.application import VitaGuardApplicationService
    from vitaguard_do.comparison.io import load_policy_record

    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "data" / "synthetic" / "multimodal" / "vitaguard_do_imagem_alpha.png",
        root / "data" / "synthetic" / "multimodal" / "vitaguard_do_imagem_beta.png",
    ]
    service = VitaGuardApplicationService(tmp_path)
    job_id, job_dir, paths = service.prepare_live_uploads([(p.name, p.read_bytes()) for p in sources])
    base = load_policy_record(root / "data" / "demo" / "structured" / "vitaguard_do_executive_plus.structured.json")

    class FakeProvider(FakeMultimodal):
        model = "fake-multimodal"
        model_summary = "fake-multimodal"

        def __init__(self, api_key=None):
            super().__init__()
            self.api_key = api_key

    class FakePipeline:
        def __init__(self, provider, output_dir):
            self.provider = provider
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)

        def cache_path(self, document):
            return self.output_dir / f"{Path(document.source_name).stem}.structured.json"

        def extract(self, document, use_cache=True, force=False):
            policy = base.model_copy(deep=True)
            policy.policy_id = document.document_id
            policy.source_documents[0].document_id = document.document_id
            policy.source_documents[0].source_file = document.source_name
            policy.source_documents[0].sha256 = document.source_sha256
            policy.source_documents[0].page_count = document.page_count
            self.cache_path(document).write_text(policy.model_dump_json(indent=2), encoding="utf-8")
            return policy, SimpleNamespace(warnings=[])

    bundle = service.analyze_live(
        job_id=job_id,
        job_dir=job_dir,
        paths=paths,
        api_key="not-persisted",
        provider_factory=FakeProvider,
        pipeline_factory=FakePipeline,
    )
    assert len(bundle.documents) == 2
    assert all(item.source_kind == "IMAGE" for item in bundle.documents)
    assert all(item.multimodal_text_pages == 1 for item in bundle.documents)
    assert service.compare_live(bundle).summary.policy_count == 2

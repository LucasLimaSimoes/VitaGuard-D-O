from pathlib import Path

from vitaguard_do.extraction.models import CoreExtraction
from vitaguard_do.extraction.pipeline import StructuredExtractionPipeline
from vitaguard_do.ingestion.pdf import ingest_pdf


class DummyProvider:
    provider_name = "dummy"
    model = "dummy-model"

    def generate_structured(self, prompt, schema):
        raise AssertionError("provider should not be called when stage cache is valid")


def test_stage_cache_roundtrip(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    pdf = project_root / "data" / "synthetic" / "vitaguard_do_essencial.pdf"
    document = ingest_pdf(pdf)
    pipeline = StructuredExtractionPipeline(DummyProvider(), output_dir=tmp_path)

    value = CoreExtraction(
        policy_id_hint="vita-test",
        scalar_facts=[],
        financial_facts=[],
        warnings=[],
    )

    pipeline._save_stage_cache(document, "core", value)
    loaded = pipeline._load_stage_cache(document, "core", CoreExtraction)
    assert loaded == value

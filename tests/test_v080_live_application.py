from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from vitaguard_do import __version__
from vitaguard_do.application import VitaGuardApplicationService
from vitaguard_do.application.live import LiveAnalysisBundle, prepare_live_uploads
from vitaguard_do.comparison.io import load_policy_record

ROOT = Path(__file__).resolve().parents[1]


def test_version_v081():
    assert __version__ == "1.0.0"


def test_prepare_live_uploads_is_deterministic_and_safe(tmp_path):
    files = [
        ("../Apolice A.pdf", b"%PDF-fake-a"),
        ("Apolice B.pdf", b"%PDF-fake-b"),
    ]
    job1, job_dir1, paths1 = prepare_live_uploads(tmp_path, files)
    job2, job_dir2, paths2 = prepare_live_uploads(tmp_path, files)
    assert job1 == job2
    assert job_dir1 == job_dir2
    assert len(paths1) == 2
    assert all(p.parent.name == "input" for p in paths1)
    assert all(".." not in p.name for p in paths1)
    assert [p.read_bytes() for p in paths2] == [b"%PDF-fake-a", b"%PDF-fake-b"]




def test_prepare_live_uploads_accepts_images(tmp_path):
    files = [("pagina 1.png", b"fake-image"), ("pagina 2.jpg", b"fake-image-2")]
    _, _, paths = prepare_live_uploads(tmp_path, files)
    assert [p.suffix for p in paths] == [".png", ".jpg"]

def test_live_pipeline_orchestration_without_external_api(tmp_path):
    # Usa PDFs sintéticos reais para exercitar PyMuPDF/ingestão, mas substitui
    # somente o provider/pipeline LLM por fakes determinísticos.
    source_pdfs = [
        ROOT / "data" / "synthetic" / "vitaguard_do_essencial.pdf",
        ROOT / "data" / "synthetic" / "vitaguard_do_executive_plus.pdf",
    ]
    files = [(p.name, p.read_bytes()) for p in source_pdfs]
    service = VitaGuardApplicationService(tmp_path)
    job_id, job_dir, paths = service.prepare_live_uploads(files)

    base = load_policy_record(ROOT / "data" / "demo" / "structured" / "vitaguard_do_executive_plus.structured.json")

    class FakeProvider:
        model_summary = "fake-model"
        model = "fake-model"
        def __init__(self, api_key=None):
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

    events = []
    bundle = service.analyze_live(
        job_id=job_id,
        job_dir=job_dir,
        paths=paths,
        api_key="not-persisted",
        progress=lambda event, message: events.append((event, message)),
        provider_factory=FakeProvider,
        pipeline_factory=FakePipeline,
    )

    assert isinstance(bundle, LiveAnalysisBundle)
    assert bundle.model == "fake-model"
    assert len(bundle.documents) == 2
    assert all(Path(x.ingested_file).exists() for x in bundle.documents)
    assert all(Path(x.structured_file).exists() for x in bundle.documents)
    assert any(event == "ingest" for event, _ in events)
    assert any(event == "extract" for event, _ in events)
    assert any(event == "done" for event, _ in events)

    overviews = service.list_live_policies(bundle)
    assert len(overviews) == 2
    report = service.compare_live(bundle)
    assert report.summary.policy_count == 2

    # Manifesto do job não deve conter a chave usada na chamada.
    manifest = (Path(bundle.job_dir) / "manifest.json").read_text(encoding="utf-8")
    assert "not-persisted" not in manifest


def test_launcher_installs_full_live_dependencies():
    launcher = (ROOT / "run_vitaguard.bat").read_text(encoding="utf-8")
    assert "requirements.txt" in launcher
    assert "requirements-ui.txt" not in launcher
    assert "validate_v100.py" in launcher
    assert "pymupdf" in launcher
    assert "google import genai" in launcher

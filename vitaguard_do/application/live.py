from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Callable, Iterable

from pydantic import BaseModel, Field

from vitaguard_do.models.schema import PolicyRecord


LiveProgressCallback = Callable[[str, str], None]


_ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class LiveDocumentArtifact(BaseModel):
    source_name: str
    document_id: str
    policy_id: str
    source_file: str
    ingested_file: str
    structured_file: str
    source_kind: str = "PDF"
    source_mime_type: str = "application/pdf"
    page_count: int = Field(ge=1)
    native_text_pages: int = Field(ge=0)
    multimodal_text_pages: int = Field(default=0, ge=0)
    low_text_pages: int = Field(ge=0)
    empty_pages: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


class LiveAnalysisBundle(BaseModel):
    job_id: str
    job_dir: str
    model: str
    documents: list[LiveDocumentArtifact] = Field(min_length=1)

    @property
    def policy_ids(self) -> list[str]:
        return [item.policy_id for item in self.documents]


class LiveInputError(ValueError):
    pass


class NativeTextUnavailableError(RuntimeError):
    """Mantida por compatibilidade com versões anteriores do frontend."""


class MultimodalTextUnavailableError(RuntimeError):
    pass


def _safe_filename(name: str, fallback_index: int) -> str:
    raw = Path(name or f"documento_{fallback_index}.pdf").name
    suffix = Path(raw).suffix.casefold()
    if suffix not in _ALLOWED_SUFFIXES:
        suffix = ".pdf"
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(raw).stem).strip(" ._") or f"documento_{fallback_index}"
    return f"{stem}{suffix}"


def _job_id(files: Iterable[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    for name, payload in files:
        h.update(name.encode("utf-8", errors="replace"))
        h.update(b"\0")
        h.update(payload)
        h.update(b"\0")
    return h.hexdigest()[:16]


def prepare_live_uploads(
    root: str | Path,
    files: list[tuple[str, bytes]],
) -> tuple[str, Path, list[Path]]:
    if len(files) < 1:
        raise LiveInputError("Nenhum documento foi enviado.")

    normalized: list[tuple[str, bytes]] = []
    for name, payload in files:
        if not payload:
            raise LiveInputError(f"O arquivo {name!r} está vazio.")
        suffix = Path(name).suffix.casefold()
        if suffix not in _ALLOWED_SUFFIXES:
            raise LiveInputError(
                f"Formato não suportado em {name!r}. Use PDF, PNG, JPG/JPEG ou WEBP."
            )
        normalized.append((name, payload))

    job_id = _job_id(normalized)
    job_dir = Path(root).resolve() / "outputs" / "live" / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    used: set[str] = set()
    paths: list[Path] = []
    for idx, (name, payload) in enumerate(normalized, start=1):
        safe = _safe_filename(name, idx)
        candidate = safe
        n = 2
        while candidate.casefold() in used:
            candidate = f"{Path(safe).stem}_{n}{Path(safe).suffix}"
            n += 1
        used.add(candidate.casefold())
        path = input_dir / candidate
        path.write_bytes(payload)
        paths.append(path)

    return job_id, job_dir, paths


def analyze_live_paths(
    *,
    root: str | Path,
    job_id: str,
    job_dir: str | Path,
    paths: list[str | Path],
    api_key: str | None,
    progress: LiveProgressCallback | None = None,
    force: bool = False,
    provider_factory=None,
    pipeline_factory=None,
) -> LiveAnalysisBundle:
    if not paths:
        raise LiveInputError("Nenhum documento para analisar.")

    # Imports pesados são tardios: o modo Demonstração não exige PyMuPDF/google-genai.
    from vitaguard_do.extraction.pipeline import StructuredExtractionPipeline
    from vitaguard_do.extraction.provider import GeminiProvider
    from vitaguard_do.ingestion.multimodal import MultimodalIngestionError, ingest_document
    from vitaguard_do.ingestion.pdf import save_ingested_document

    provider_factory = provider_factory or GeminiProvider
    pipeline_factory = pipeline_factory or StructuredExtractionPipeline

    root = Path(root).resolve()
    job_dir = Path(job_dir).resolve()
    ingestion_dir = job_dir / "ingested"
    structured_dir = job_dir / "structured"
    multimodal_cache_dir = job_dir / "multimodal_cache"
    ingestion_dir.mkdir(parents=True, exist_ok=True)
    structured_dir.mkdir(parents=True, exist_ok=True)

    provider = provider_factory(api_key=api_key)
    pipeline = pipeline_factory(provider, output_dir=structured_dir)
    artifacts: list[LiveDocumentArtifact] = []

    for idx, raw_path in enumerate(paths, start=1):
        path = Path(raw_path).resolve()
        if progress:
            progress("ingest", f"{idx}/{len(paths)} · Lendo {path.name}")

        try:
            document = ingest_document(
                path,
                extractor=provider,
                cache_dir=multimodal_cache_dir,
                force=force,
                progress=progress,
            )
        except MultimodalIngestionError as exc:
            raise MultimodalTextUnavailableError(str(exc)) from exc

        if document.stats.total_clean_chars <= 0 or not document.chunks:
            raise MultimodalTextUnavailableError(
                f"{path.name} não produziu texto utilizável para a extração estruturada."
            )

        ingested_file = ingestion_dir / f"{path.stem}.ingested.json"
        save_ingested_document(document, ingested_file)

        if progress:
            source_note = (
                f"{document.stats.multimodal_text_pages} página(s) via multimodal · "
                if document.stats.multimodal_text_pages
                else ""
            )
            progress(
                "extract",
                f"{idx}/{len(paths)} · {source_note}extração semântica com Gemini em {path.name}. "
                "As etapas concluídas ficam em cache para retomada.",
            )

        policy, run = pipeline.extract(document, use_cache=True, force=force)
        structured_file = pipeline.cache_path(document)

        warnings = list(dict.fromkeys([*document.warnings, *run.warnings, *policy.extraction.warnings]))
        suffix = path.suffix.casefold()
        artifacts.append(
            LiveDocumentArtifact(
                source_name=document.source_name,
                document_id=document.document_id,
                policy_id=policy.policy_id,
                source_file=str(path),
                ingested_file=str(ingested_file),
                structured_file=str(structured_file),
                source_kind="PDF" if suffix == ".pdf" else "IMAGE",
                source_mime_type=document.source_mime_type,
                page_count=document.page_count,
                native_text_pages=document.stats.native_text_pages,
                multimodal_text_pages=document.stats.multimodal_text_pages,
                low_text_pages=document.stats.low_text_pages,
                empty_pages=document.stats.empty_pages,
                warnings=warnings,
            )
        )
        if progress:
            progress("done", f"{idx}/{len(paths)} · {path.name} pronto para comparação")

    policy_ids = [item.policy_id for item in artifacts]
    duplicate_ids = sorted({pid for pid in policy_ids if policy_ids.count(pid) > 1})
    if duplicate_ids:
        raise LiveInputError(
            "Foram produzidos policy_id duplicados. Verifique se o mesmo documento/apólice "
            f"foi enviado mais de uma vez: {duplicate_ids}"
        )

    model = getattr(provider, "model_summary", getattr(provider, "model", "Gemini"))
    bundle = LiveAnalysisBundle(
        job_id=job_id,
        job_dir=str(job_dir),
        model=str(model),
        documents=artifacts,
    )
    (job_dir / "manifest.json").write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    return bundle


def clear_live_job(bundle: LiveAnalysisBundle) -> None:
    path = Path(bundle.job_dir)
    if path.exists():
        shutil.rmtree(path)


def load_live_policy(artifact: LiveDocumentArtifact) -> PolicyRecord:
    from vitaguard_do.comparison.io import load_policy_record

    return load_policy_record(artifact.structured_file)

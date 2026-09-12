from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from .models import (
    IngestedDocument,
    IngestedPage,
    IngestionConfig,
    IngestionStats,
    PageTextOrigin,
    PageTextStatus,
)
from .pdf import build_document_id, fitz, ingest_pdf, sha256_file
from .text import (
    chunk_page_text,
    classify_page_text,
    detect_repeated_marginal_lines,
    normalize_extracted_text,
    remove_marginal_lines,
    sha256_text,
)


SUPPORTED_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
SUPPORTED_INPUT_SUFFIXES = {".pdf", *SUPPORTED_IMAGE_MIME_TYPES.keys()}

IngestionProgressCallback = Callable[[str, str], None]


class MultimodalTextExtractor(Protocol):
    def transcribe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        source_name: str = "",
        page_number: int | None = None,
    ) -> str:
        ...


class MultimodalIngestionError(RuntimeError):
    pass


def _ocr_cache_path(cache_dir: Path | None, document_id: str, page_number: int) -> Path | None:
    if cache_dir is None:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{document_id}.p{page_number:04d}.txt"


def _transcribe_cached(
    *,
    extractor: MultimodalTextExtractor,
    image_bytes: bytes,
    mime_type: str,
    source_name: str,
    page_number: int,
    document_id: str,
    cache_dir: Path | None,
    force: bool,
) -> tuple[str, bool]:
    cache_path = _ocr_cache_path(cache_dir, document_id, page_number)
    if cache_path is not None and cache_path.exists() and not force:
        return normalize_extracted_text(cache_path.read_text(encoding="utf-8")), True

    text = extractor.transcribe_image(
        image_bytes,
        mime_type,
        source_name=source_name,
        page_number=page_number,
    )
    text = normalize_extracted_text(text or "")
    if cache_path is not None:
        cache_path.write_text(text, encoding="utf-8")
    return text, False


def _build_document(
    *,
    path: Path,
    document_id: str,
    file_hash: str,
    source_mime_type: str,
    raw_page_texts: list[str],
    origins: list[PageTextOrigin],
    config: IngestionConfig,
    pdf_metadata: dict[str, str | None] | None = None,
    base_warnings: list[str] | None = None,
) -> IngestedDocument:
    if not raw_page_texts:
        raise MultimodalIngestionError(f"Nenhuma página disponível para {path.name}.")
    if len(raw_page_texts) != len(origins):
        raise ValueError("raw_page_texts/origins size mismatch")

    repeated_keys = detect_repeated_marginal_lines(raw_page_texts, config)
    pages: list[IngestedPage] = []
    chunks = []
    all_removed: list[str] = []

    for page_number, (raw_text, origin) in enumerate(zip(raw_page_texts, origins), start=1):
        raw_text = normalize_extracted_text(raw_text)
        clean_text, removed = remove_marginal_lines(raw_text, repeated_keys, config)
        status = classify_page_text(clean_text, config.low_text_threshold)
        warnings: list[str] = []
        if status == PageTextStatus.EMPTY:
            warnings.append("Nenhum texto utilizável foi recuperado nesta página.")
        elif status == PageTextStatus.LOW_TEXT:
            warnings.append("Pouco texto foi recuperado nesta página; revise as evidências com atenção.")
        if origin == PageTextOrigin.GEMINI_MULTIMODAL:
            warnings.append("Texto recuperado por leitura multimodal Gemini.")

        page = IngestedPage(
            page_number=page_number,
            status=status,
            text_origin=origin,
            raw_text=raw_text,
            clean_text=clean_text,
            raw_char_count=len(raw_text),
            clean_char_count=len(clean_text),
            sha256=sha256_text(clean_text),
            removed_marginal_lines=removed,
            warnings=warnings,
        )
        pages.append(page)
        all_removed.extend(removed)
        chunks.extend(
            chunk_page_text(
                document_id=document_id,
                page_number=page_number,
                text=clean_text,
                config=config,
            )
        )

    native_text_pages = sum(
        p.text_origin == PageTextOrigin.NATIVE_PDF and p.status == PageTextStatus.NATIVE_TEXT
        for p in pages
    )
    multimodal_text_pages = sum(
        p.text_origin == PageTextOrigin.GEMINI_MULTIMODAL and p.clean_char_count > 0
        for p in pages
    )
    stats = IngestionStats(
        page_count=len(pages),
        native_text_pages=native_text_pages,
        multimodal_text_pages=multimodal_text_pages,
        low_text_pages=sum(p.status == PageTextStatus.LOW_TEXT for p in pages),
        empty_pages=sum(p.status == PageTextStatus.EMPTY for p in pages),
        total_raw_chars=sum(p.raw_char_count for p in pages),
        total_clean_chars=sum(p.clean_char_count for p in pages),
        chunk_count=len(chunks),
        repeated_marginal_lines_detected=len(repeated_keys),
    )

    warnings = list(base_warnings or [])
    if multimodal_text_pages:
        warnings.append(
            f"{multimodal_text_pages} página(s) recuperada(s) por leitura multimodal Gemini."
        )
    unresolved = stats.low_text_pages + stats.empty_pages
    if unresolved:
        warnings.append(
            f"{unresolved} página(s) permaneceram com pouco ou nenhum texto após a ingestão."
        )
    warnings = list(dict.fromkeys(warnings))

    return IngestedDocument(
        ingestion_version="0.8.1.1",
        document_id=document_id,
        source_file=str(path),
        source_name=path.name,
        source_sha256=file_hash,
        source_mime_type=source_mime_type,
        page_count=len(pages),
        pdf_metadata=pdf_metadata or {},
        config=config,
        repeated_marginal_lines=sorted(set(all_removed), key=str.casefold),
        pages=pages,
        chunks=chunks,
        stats=stats,
        warnings=warnings,
    )


def _render_pdf_page_png(path: Path, page_index: int, *, dpi: int = 160) -> bytes:
    with fitz.open(path) as doc:
        page = doc[page_index]
        scale = max(1.0, float(dpi) / 72.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.tobytes("png")


def ingest_pdf_with_multimodal_fallback(
    path: str | Path,
    *,
    extractor: MultimodalTextExtractor,
    document_id: str | None = None,
    config: IngestionConfig | None = None,
    cache_dir: str | Path | None = None,
    force: bool = False,
    progress: IngestionProgressCallback | None = None,
) -> IngestedDocument:
    path = Path(path)
    config = config or IngestionConfig()
    native = ingest_pdf(path, document_id=document_id, config=config)

    needs_fallback = [
        p.page_number
        for p in native.pages
        if p.status in {PageTextStatus.LOW_TEXT, PageTextStatus.EMPTY}
    ]
    if not needs_fallback:
        return native

    raw_page_texts = [page.raw_text for page in native.pages]
    origins = [PageTextOrigin.NATIVE_PDF for _ in native.pages]
    cache = Path(cache_dir) if cache_dir is not None else None

    for page_number in needs_fallback:
        if progress:
            progress(
                "multimodal",
                f"{path.name} · página {page_number}/{native.page_count}: leitura multimodal Gemini",
            )
        image_bytes = _render_pdf_page_png(path, page_number - 1)
        text, from_cache = _transcribe_cached(
            extractor=extractor,
            image_bytes=image_bytes,
            mime_type="image/png",
            source_name=path.name,
            page_number=page_number,
            document_id=native.document_id,
            cache_dir=cache,
            force=force,
        )
        if progress and from_cache:
            progress(
                "multimodal_cache",
                f"{path.name} · página {page_number}: texto multimodal reaproveitado do cache",
            )
        if text:
            raw_page_texts[page_number - 1] = text
            origins[page_number - 1] = PageTextOrigin.GEMINI_MULTIMODAL

    resolved = _build_document(
        path=path.resolve(),
        document_id=native.document_id,
        file_hash=native.source_sha256,
        source_mime_type="application/pdf",
        raw_page_texts=raw_page_texts,
        origins=origins,
        config=config,
        pdf_metadata=native.pdf_metadata,
        base_warnings=[],
    )
    if resolved.stats.total_clean_chars <= 0 or not resolved.chunks:
        raise MultimodalIngestionError(
            f"{path.name} não produziu texto utilizável nem após a leitura multimodal."
        )
    return resolved


def ingest_image_with_multimodal(
    path: str | Path,
    *,
    extractor: MultimodalTextExtractor,
    document_id: str | None = None,
    config: IngestionConfig | None = None,
    cache_dir: str | Path | None = None,
    force: bool = False,
    progress: IngestionProgressCallback | None = None,
) -> IngestedDocument:
    path = Path(path)
    suffix = path.suffix.casefold()
    mime_type = SUPPORTED_IMAGE_MIME_TYPES.get(suffix)
    if mime_type is None:
        raise ValueError(f"Formato de imagem não suportado: {path.name}")

    config = config or IngestionConfig()
    file_hash = sha256_file(path)
    document_id = document_id or build_document_id(path, file_hash)
    if progress:
        progress("multimodal", f"{path.name} · lendo imagem com Gemini multimodal")

    text, from_cache = _transcribe_cached(
        extractor=extractor,
        image_bytes=path.read_bytes(),
        mime_type=mime_type,
        source_name=path.name,
        page_number=1,
        document_id=document_id,
        cache_dir=Path(cache_dir) if cache_dir is not None else None,
        force=force,
    )
    if progress and from_cache:
        progress("multimodal_cache", f"{path.name} · texto multimodal reaproveitado do cache")

    document = _build_document(
        path=path.resolve(),
        document_id=document_id,
        file_hash=file_hash,
        source_mime_type=mime_type,
        raw_page_texts=[text],
        origins=[PageTextOrigin.GEMINI_MULTIMODAL],
        config=config,
        pdf_metadata={},
        base_warnings=[],
    )
    if document.stats.total_clean_chars <= 0 or not document.chunks:
        raise MultimodalIngestionError(
            f"{path.name} não produziu texto utilizável na leitura multimodal."
        )
    return document


def ingest_document(
    path: str | Path,
    *,
    extractor: MultimodalTextExtractor,
    document_id: str | None = None,
    config: IngestionConfig | None = None,
    cache_dir: str | Path | None = None,
    force: bool = False,
    progress: IngestionProgressCallback | None = None,
) -> IngestedDocument:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return ingest_pdf_with_multimodal_fallback(
            path,
            extractor=extractor,
            document_id=document_id,
            config=config,
            cache_dir=cache_dir,
            force=force,
            progress=progress,
        )
    if suffix in SUPPORTED_IMAGE_MIME_TYPES:
        return ingest_image_with_multimodal(
            path,
            extractor=extractor,
            document_id=document_id,
            config=config,
            cache_dir=cache_dir,
            force=force,
            progress=progress,
        )
    raise ValueError(
        f"Formato não suportado: {path.name}. Use PDF, PNG, JPG/JPEG ou WEBP."
    )

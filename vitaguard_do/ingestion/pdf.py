from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

try:
    import pymupdf as fitz  # API moderna do PyMuPDF
except ModuleNotFoundError:
    import warnings
    try:
        # Algumas imagens Colab ainda expõem apenas o alias legado `fitz`.
        # Ele é suficiente para nosso uso; o warning de depreciação é
        # suprimido para não poluir a demonstração.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r".*`fitz` API is deprecated.*",
            )
            import fitz  # type: ignore[no-redef]
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "PyMuPDF/fitz nao esta disponivel. Execute a celula "
            "'Preparar dependencias' do notebook antes da validacao."
        ) from exc

from .models import IngestedDocument, IngestedPage, IngestionConfig, IngestionStats
from .text import (
    chunk_page_text,
    classify_page_text,
    detect_repeated_marginal_lines,
    normalize_extracted_text,
    remove_marginal_lines,
    sha256_text,
)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _slugify(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "document"


def build_document_id(path: str | Path, file_sha256: str) -> str:
    return f"{_slugify(Path(path).stem)}-{file_sha256[:10]}"


def _clean_metadata(metadata: dict | None) -> dict[str, str | None]:
    if not metadata:
        return {}
    allowed = ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate")
    return {key: metadata.get(key) for key in allowed if key in metadata}


def ingest_pdf(
    path: str | Path,
    *,
    document_id: str | None = None,
    config: IngestionConfig | None = None,
) -> IngestedDocument:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.casefold() != ".pdf":
        raise ValueError(f"v0.3 accepts PDF input only: {path.name}")

    config = config or IngestionConfig()
    file_hash = sha256_file(path)
    document_id = document_id or build_document_id(path, file_hash)

    with fitz.open(path) as doc:
        if doc.page_count < 1:
            raise ValueError(f"PDF has no pages: {path}")

        raw_normalized = [
            normalize_extracted_text(page.get_text("text", sort=True))
            for page in doc
        ]
        repeated_keys = detect_repeated_marginal_lines(raw_normalized, config)

        pages: list[IngestedPage] = []
        chunks = []
        all_removed = []

        for page_number, raw_text in enumerate(raw_normalized, start=1):
            clean_text, removed = remove_marginal_lines(raw_text, repeated_keys, config)
            status = classify_page_text(clean_text, config.low_text_threshold)
            warnings = []
            if status.value == "EMPTY":
                warnings.append("No native text extracted; the v0.8.1.1 live flow can apply multimodal fallback.")
            elif status.value == "LOW_TEXT":
                warnings.append("Very little native text extracted; the v0.8.1.1 live flow may apply multimodal fallback.")

            page = IngestedPage(
                page_number=page_number,
                status=status,
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

        from .models import PageTextStatus

        stats = IngestionStats(
            page_count=doc.page_count,
            native_text_pages=sum(p.status == PageTextStatus.NATIVE_TEXT for p in pages),
            low_text_pages=sum(p.status == PageTextStatus.LOW_TEXT for p in pages),
            empty_pages=sum(p.status == PageTextStatus.EMPTY for p in pages),
            total_raw_chars=sum(p.raw_char_count for p in pages),
            total_clean_chars=sum(p.clean_char_count for p in pages),
            chunk_count=len(chunks),
            repeated_marginal_lines_detected=len(repeated_keys),
        )

        warnings = []
        if stats.low_text_pages or stats.empty_pages:
            warnings.append(
                f"{stats.low_text_pages + stats.empty_pages} page(s) may need multimodal fallback."
            )

        return IngestedDocument(
            document_id=document_id,
            source_file=str(path),
            source_name=path.name,
            source_sha256=file_hash,
            page_count=doc.page_count,
            pdf_metadata=_clean_metadata(doc.metadata),
            config=config,
            repeated_marginal_lines=sorted(set(all_removed), key=str.casefold),
            pages=pages,
            chunks=chunks,
            stats=stats,
            warnings=warnings,
        )


def save_ingested_document(document: IngestedDocument, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        document.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return output_path

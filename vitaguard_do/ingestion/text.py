from __future__ import annotations

import hashlib
import re
from collections import Counter

from .models import IngestionConfig, PageTextStatus, TextChunk


_WS_RE = re.compile(r"[ \t\u00a0]+")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_extracted_text(text: str) -> str:
    """Normalize PDF text while preserving useful paragraph boundaries."""
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for raw_line in text.split("\n"):
        line = _WS_RE.sub(" ", raw_line).strip()
        lines.append(line)
    text = "\n".join(lines)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def classify_page_text(text: str, low_text_threshold: int) -> PageTextStatus:
    n = len(text.strip())
    if n == 0:
        return PageTextStatus.EMPTY
    if n < low_text_threshold:
        return PageTextStatus.LOW_TEXT
    return PageTextStatus.NATIVE_TEXT


def _normalize_margin_candidate(line: str) -> str:
    line = _WS_RE.sub(" ", line).strip()
    # Page numbers alone are intentionally normalized to one token so they can
    # be detected as the same repeated footer across pages.
    if re.fullmatch(r"(?:p[aá]g(?:ina)?\.?\s*)?\d+(?:\s*/\s*\d+)?", line, re.IGNORECASE):
        return "<PAGE_NUMBER>"
    return line.casefold()


def detect_repeated_marginal_lines(
    page_texts: list[str],
    config: IngestionConfig,
) -> set[str]:
    """Detect conservative repeated header/footer lines across pages."""
    if not config.remove_repeated_marginal_lines:
        return set()

    occurrence = Counter()
    display = {}
    nonempty_pages = 0

    for text in page_texts:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            continue
        nonempty_pages += 1
        candidates = lines[: config.marginal_line_window] + lines[-config.marginal_line_window :]
        seen_on_page = set()
        for line in candidates:
            if len(line) > config.repeated_line_max_chars:
                continue
            key = _normalize_margin_candidate(line)
            if not key or key in seen_on_page:
                continue
            seen_on_page.add(key)
            occurrence[key] += 1
            display.setdefault(key, line)

    if nonempty_pages == 0:
        return set()

    needed_by_ratio = max(1, int(nonempty_pages * config.repeated_line_min_ratio + 0.999999))
    needed = max(config.repeated_line_min_pages, needed_by_ratio)
    return {key for key, count in occurrence.items() if count >= needed}


def remove_marginal_lines(text: str, repeated_keys: set[str], config: IngestionConfig) -> tuple[str, list[str]]:
    if not repeated_keys or not text.strip():
        return text.strip(), []

    lines = text.splitlines()
    nonempty_positions = [i for i, line in enumerate(lines) if line.strip()]
    if not nonempty_positions:
        return "", []

    margin_positions = set(nonempty_positions[: config.marginal_line_window])
    margin_positions.update(nonempty_positions[-config.marginal_line_window :])

    removed = []
    kept = []
    for i, line in enumerate(lines):
        if i in margin_positions and _normalize_margin_candidate(line) in repeated_keys:
            removed.append(line.strip())
            continue
        kept.append(line)

    return normalize_extracted_text("\n".join(kept)), removed


def _move_to_word_start(text: str, pos: int) -> int:
    pos = min(max(pos, 0), len(text))
    while pos < len(text) and pos > 0 and not text[pos - 1].isspace() and not text[pos].isspace():
        pos += 1
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _choose_end(text: str, start: int, target_end: int) -> int:
    if target_end >= len(text):
        return len(text)

    # Prefer ending at a paragraph/newline/space close to the size target.
    search_start = max(start + 1, target_end - 500)
    region = text[search_start:target_end]
    for sep in ("\n\n", "\n", ". ", "; ", ", ", " "):
        idx = region.rfind(sep)
        if idx != -1:
            end = search_start + idx + len(sep)
            if end > start:
                return end
    return target_end


def chunk_page_text(
    *,
    document_id: str,
    page_number: int,
    text: str,
    config: IngestionConfig,
) -> list[TextChunk]:
    """Split one cleaned page into traceable overlapping character chunks."""
    if not text.strip():
        return []

    chunks: list[TextChunk] = []
    start = 0
    page_len = len(text)
    index = 0

    while start < page_len:
        target_end = min(page_len, start + config.max_chunk_chars)
        end = _choose_end(text, start, target_end)

        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end <= start:
            break

        chunk_text = text[start:end]
        chunk_id = f"{document_id}:p{page_number:04d}:c{index:03d}"
        chunks.append(
            TextChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                page_number=page_number,
                chunk_index_on_page=index,
                char_start=start,
                char_end=end,
                text=chunk_text,
                sha256=sha256_text(chunk_text),
            )
        )
        if end >= page_len:
            break

        next_start = max(end - config.overlap_chars, start + 1)
        next_start = _move_to_word_start(text, next_start)
        if next_start <= start:
            next_start = end
        start = next_start
        index += 1

    return chunks

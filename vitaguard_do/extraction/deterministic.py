from __future__ import annotations

import re
from dataclasses import dataclass

from vitaguard_do.ingestion.models import IngestedDocument
from vitaguard_do.models.schema import Evidence


@dataclass(frozen=True)
class DeterministicScalar:
    value: str
    evidence: Evidence
    raw_value: str


_SUSEP_RE = re.compile(
    r"(?:Processo\s+SUSEP\s*(?:n[ºo°.]*)?\s*[:\-]?\s*)?"
    r"(?P<process>\d{5}\.\d{6}/\d{4}-\d{2})",
    flags=re.IGNORECASE,
)

_VERSION_RE = re.compile(
    r"Vers(?:ã|a)o\s+(?P<version>"
    r"(?:janeiro|fevereiro|mar(?:ç|c)o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
    r"\s*/\s*\d{4}|\d{4}-\d{2})",
    flags=re.IGNORECASE,
)

_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _line_containing(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    return text[line_start:line_end].strip()


def find_susep_process(document: IngestedDocument) -> DeterministicScalar | None:
    # Search raw text on purpose. Repeated footer cleanup may remove the SUSEP
    # line from clean_text, as happens in the Allianz 12/2025 document.
    for page in document.pages:
        match = _SUSEP_RE.search(page.raw_text)
        if not match:
            continue
        process = match.group("process")
        excerpt = _line_containing(page.raw_text, match.start(), match.end())
        return DeterministicScalar(
            value=process,
            raw_value=process,
            evidence=Evidence(
                document_id=document.document_id,
                page=page.page_number,
                section="Processo SUSEP",
                excerpt=excerpt or process,
                chunk_id=None,
            ),
        )
    return None


def canonicalize_document_version(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().casefold()
    iso = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if iso:
        month = int(iso.group(2))
        if 1 <= month <= 12:
            return f"{iso.group(1)}-{month:02d}"
        return value.strip()

    text = text.replace(" ", "")
    if "/" not in text:
        return value.strip()
    month_name, year = text.split("/", 1)
    month = _MONTHS.get(month_name)
    if month and re.fullmatch(r"\d{4}", year):
        return f"{year}-{month:02d}"
    return value.strip()


def find_document_version(document: IngestedDocument) -> DeterministicScalar | None:
    for page in document.pages[:8]:
        match = _VERSION_RE.search(page.raw_text)
        if not match:
            continue
        raw = match.group("version").strip()
        normalized = canonicalize_document_version(raw) or raw
        excerpt = _line_containing(page.raw_text, match.start(), match.end())
        return DeterministicScalar(
            value=normalized,
            raw_value=raw,
            evidence=Evidence(
                document_id=document.document_id,
                page=page.page_number,
                section="Versão do documento",
                excerpt=excerpt or raw,
                chunk_id=None,
            ),
        )
    return None

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class PageTextStatus(str, Enum):
    NATIVE_TEXT = "NATIVE_TEXT"
    LOW_TEXT = "LOW_TEXT"
    EMPTY = "EMPTY"


class PageTextOrigin(str, Enum):
    NATIVE_PDF = "NATIVE_PDF"
    GEMINI_MULTIMODAL = "GEMINI_MULTIMODAL"


class IngestionConfig(BaseModel):
    max_chunk_chars: int = Field(default=3000, ge=500, le=12000)
    overlap_chars: int = Field(default=250, ge=0, le=2000)
    low_text_threshold: int = Field(default=80, ge=0, le=2000)

    remove_repeated_marginal_lines: bool = True
    marginal_line_window: int = Field(default=3, ge=1, le=8)
    repeated_line_min_pages: int = Field(default=3, ge=2, le=50)
    repeated_line_min_ratio: float = Field(default=0.60, ge=0.25, le=1.0)
    repeated_line_max_chars: int = Field(default=140, ge=10, le=500)

    @model_validator(mode="after")
    def validate_chunk_overlap(self):
        if self.overlap_chars >= self.max_chunk_chars:
            raise ValueError("overlap_chars must be smaller than max_chunk_chars")
        return self


class IngestedPage(BaseModel):
    page_number: int = Field(ge=1)
    status: PageTextStatus
    text_origin: PageTextOrigin = PageTextOrigin.NATIVE_PDF
    raw_text: str
    clean_text: str
    raw_char_count: int = Field(ge=0)
    clean_char_count: int = Field(ge=0)
    sha256: str
    removed_marginal_lines: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TextChunk(BaseModel):
    chunk_id: str
    document_id: str
    page_number: int = Field(ge=1)
    chunk_index_on_page: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    text: str
    sha256: str

    @model_validator(mode="after")
    def validate_offsets(self):
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        if not self.text:
            raise ValueError("chunk text must not be empty")
        return self


class IngestionStats(BaseModel):
    page_count: int = Field(ge=1)
    native_text_pages: int = Field(ge=0)
    multimodal_text_pages: int = Field(default=0, ge=0)
    low_text_pages: int = Field(ge=0)
    empty_pages: int = Field(ge=0)
    total_raw_chars: int = Field(ge=0)
    total_clean_chars: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    repeated_marginal_lines_detected: int = Field(ge=0)


class IngestedDocument(BaseModel):
    ingestion_version: str = "0.3"
    document_id: str
    source_file: str
    source_name: str
    source_sha256: str
    source_mime_type: str = "application/pdf"
    page_count: int = Field(ge=1)
    pdf_metadata: dict[str, str | None] = Field(default_factory=dict)
    config: IngestionConfig
    repeated_marginal_lines: list[str] = Field(default_factory=list)
    pages: list[IngestedPage]
    chunks: list[TextChunk]
    stats: IngestionStats
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: list[str] = Field(default_factory=list)

    def page(self, page_number: int) -> IngestedPage:
        if not 1 <= page_number <= self.page_count:
            raise IndexError(page_number)
        return self.pages[page_number - 1]

    def chunks_for_page(self, page_number: int) -> list[TextChunk]:
        return [c for c in self.chunks if c.page_number == page_number]

    @classmethod
    def from_json_file(cls, path: str | Path) -> "IngestedDocument":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

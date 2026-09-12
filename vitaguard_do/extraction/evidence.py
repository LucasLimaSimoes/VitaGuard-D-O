from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable, Sequence

from vitaguard_do.ingestion.models import IngestedDocument
from vitaguard_do.models.schema import Evidence

from .models import (
    EvidenceIssue,
    EvidenceRef,
    EvidenceRepair,
    EvidenceRecovery,
    EvidenceValidationReport,
)


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _norm_search(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _candidate_line_windows(text: str, target_line_count: int):
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return
    low = max(1, target_line_count - 1)
    high = min(len(lines), target_line_count + 1)
    for size in range(low, high + 1):
        for start in range(0, len(lines) - size + 1):
            yield "\n".join(lines[start:start + size])


def _repair_excerpt(
    claimed: str,
    chunk_text: str,
    *,
    threshold: float = 0.97,
) -> tuple[str, float] | None:
    """Repair only very small transcription errors inside the already-claimed chunk."""
    claimed_norm = _norm_ws(claimed)
    if not claimed_norm or len(claimed_norm) < 24:
        return None

    target_line_count = max(1, len([x for x in claimed.splitlines() if x.strip()]))
    best_text = None
    best_ratio = 0.0

    for candidate in _candidate_line_windows(chunk_text, target_line_count):
        candidate_norm = _norm_ws(candidate)
        ratio = difflib.SequenceMatcher(
            None,
            claimed_norm.casefold(),
            candidate_norm.casefold(),
            autojunk=False,
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_text = candidate

    if best_text is not None and best_ratio >= threshold:
        return best_text, best_ratio
    return None


def _clean_terms(
    terms: Sequence[str] | None,
    *,
    preserve_order: bool = False,
) -> list[tuple[str, str]]:
    if not terms:
        return []
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    source = [t for t in terms if t]
    if not preserve_order:
        source = sorted(source, key=len, reverse=True)
    for term in source:
        norm = _norm_search(term)
        if len(norm) < 6 or norm in seen:
            continue
        seen.add(norm)
        result.append((term, norm))
    return result


def _window_support(text: str, terms: Sequence[str] | None) -> tuple[str, str] | None:
    """Find conservative exact semantic support in a contiguous 1-3 line window.

    Matching ignores accents/case/punctuation, but the returned excerpt is always
    copied verbatim from the source text.
    """
    cleaned = _clean_terms(terms)
    if not cleaned:
        return None
    lines = [line for line in text.splitlines() if line.strip()]
    for size in (1, 2, 3):
        for start in range(0, len(lines) - size + 1):
            window = "\n".join(lines[start:start + size])
            normalized = _norm_search(window)
            for original, term_norm in cleaned:
                if term_norm in normalized:
                    return window, original
    return None


def _formal_heading_support(
    text: str,
    terms: Sequence[str] | None,
) -> tuple[str, str, int] | None:
    """Return the strongest formal heading match in one source block.

    Numbered headings outrank plain headings. A taxonomy term may also be the
    leading phrase of a slightly longer formal title (e.g. "Cooperacao do
    Segurado"). The excerpt is always copied verbatim from the source.
    """
    cleaned = _clean_terms(terms, preserve_order=True)
    if not cleaned:
        return None
    lines = [line for line in text.splitlines() if line.strip()]
    best: tuple[str, str, int] | None = None
    for idx, line in enumerate(lines):
        normalized = _norm_search(line)
        for original, term_norm in cleaned:
            number_prefix = r"(?:\d+(?:\s+\d+)*\s+)?"
            exact = re.match(rf"^{number_prefix}{re.escape(term_norm)}$", normalized)
            prefix = re.match(
                rf"^{number_prefix}{re.escape(term_norm)}(?:\s+[a-z0-9]+){{1,6}}$",
                normalized,
            )
            if not exact and not prefix:
                continue
            numbered = bool(re.match(r"^\d+(?:\s+\d+)*\s+", normalized))
            score = 300 if (numbered and exact) else 250 if numbered else 220 if exact else 170
            window = "\n".join(lines[idx : min(len(lines), idx + 3)])
            candidate = (window, original, score)
            if best is None or candidate[2] > best[2]:
                best = candidate
    return best
    lines = [line for line in text.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        normalized = _norm_search(line)
        for original, term_norm in cleaned:
            # _norm_search converts e.g. "5.7 Custos" -> "5 7 custos".
            pattern = rf"^(?:\d+(?:\s+\d+)*\s+)?{re.escape(term_norm)}$"
            if re.match(pattern, normalized):
                # Return the heading plus up to two following source lines. This is
                # still verbatim and provides useful context for audit/recovery.
                window = "\n".join(lines[idx : min(len(lines), idx + 3)])
                return window, original
    return None


class EvidenceValidator:
    def __init__(self, document: IngestedDocument):
        self.document = document
        self._chunks = {chunk.chunk_id: chunk for chunk in document.chunks}

    def _record_issue(
        self,
        ref: EvidenceRef,
        *,
        extractor: str,
        object_type: str,
        object_name: str,
        report: EvidenceValidationReport,
        reason: str,
    ) -> None:
        report.invalid_claims += 1
        report.issues.append(EvidenceIssue(
            extractor=extractor,
            object_type=object_type,
            object_name=object_name,
            chunk_id=ref.chunk_id,
            page_number=ref.page_number,
            reason=reason,
            excerpt=ref.excerpt,
        ))

    def validate_ref(
        self,
        ref: EvidenceRef,
        *,
        extractor: str,
        object_type: str,
        object_name: str,
        report: EvidenceValidationReport,
    ) -> Evidence | None:
        report.total_claims += 1
        chunk = self._chunks.get(ref.chunk_id)
        if chunk is None:
            self._record_issue(
                ref,
                extractor=extractor,
                object_type=object_type,
                object_name=object_name,
                report=report,
                reason="chunk_id inexistente no documento ingerido",
            )
            return None

        if chunk.page_number != ref.page_number:
            self._record_issue(
                ref,
                extractor=extractor,
                object_type=object_type,
                object_name=object_name,
                report=report,
                reason=f"pagina informada {ref.page_number} difere da pagina real {chunk.page_number}",
            )
            return None

        excerpt_norm = _norm_ws(ref.excerpt)
        chunk_norm = _norm_ws(chunk.text)

        if excerpt_norm and excerpt_norm in chunk_norm:
            report.valid_claims += 1
            return Evidence(
                document_id=self.document.document_id,
                page=chunk.page_number,
                section=ref.section,
                excerpt=ref.excerpt,
                chunk_id=chunk.chunk_id,
            )

        repaired = _repair_excerpt(ref.excerpt, chunk.text)
        if repaired is not None:
            repaired_excerpt, similarity = repaired
            report.valid_claims += 1
            report.repaired_claims += 1
            report.repairs.append(EvidenceRepair(
                extractor=extractor,
                object_type=object_type,
                object_name=object_name,
                chunk_id=ref.chunk_id,
                page_number=ref.page_number,
                original_excerpt=ref.excerpt,
                repaired_excerpt=repaired_excerpt,
                similarity=similarity,
            ))
            return Evidence(
                document_id=self.document.document_id,
                page=chunk.page_number,
                section=ref.section,
                excerpt=repaired_excerpt,
                chunk_id=chunk.chunk_id,
            )

        self._record_issue(
            ref,
            extractor=extractor,
            object_type=object_type,
            object_name=object_name,
            report=report,
            reason="excerpt nao encontrado no texto do chunk (mesmo apos normalizacao e reparo conservador)",
        )
        return None

    def find_support(
        self,
        recovery_terms: Sequence[str] | None,
        *,
        preferred_page: int | None = None,
        section: str | None = None,
        prefer_formal_heading: bool = False,
    ) -> tuple[Evidence, str] | None:
        """Ground an object deterministically from exact normalized source terms.

        Search order is conservative: the claimed page first (when valid), then
        the rest of the document. Chunks are preferred because they retain a
        chunk_id. Raw page text is used as a fallback for repeated headers or
        footers that were intentionally removed during cleaning/chunking.
        """
        if not _clean_terms(recovery_terms):
            return None

        page_order: list[int] = []
        if preferred_page is not None and 1 <= preferred_page <= self.document.page_count:
            page_order.append(preferred_page)
        page_order.extend(
            p for p in range(1, self.document.page_count + 1) if p not in page_order
        )

        if prefer_formal_heading:
            # Rank formal headings globally instead of accepting the first textual
            # occurrence. This avoids grounding an item through an earlier
            # cross-reference when a stronger numbered section heading exists later.
            formal_candidates: list[tuple[int, int, Evidence, str]] = []
            for page_number in page_order:
                preferred_bonus = 20 if page_number == preferred_page else 0
                for chunk in self.document.chunks_for_page(page_number):
                    found = _formal_heading_support(chunk.text, recovery_terms)
                    if found:
                        excerpt, matched_term, heading_score = found
                        formal_candidates.append((
                            heading_score + preferred_bonus,
                            -page_number,
                            Evidence(
                                document_id=self.document.document_id,
                                page=page_number,
                                section=section,
                                excerpt=excerpt,
                                chunk_id=chunk.chunk_id,
                            ),
                            matched_term,
                        ))
                page = self.document.page(page_number)
                found = _formal_heading_support(page.raw_text, recovery_terms)
                if found:
                    excerpt, matched_term, heading_score = found
                    formal_candidates.append((
                        heading_score + preferred_bonus - 2,
                        -page_number,
                        Evidence(
                            document_id=self.document.document_id,
                            page=page_number,
                            section=section,
                            excerpt=excerpt,
                            chunk_id=None,
                        ),
                        matched_term,
                    ))
            if formal_candidates:
                formal_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
                _, _, evidence, matched_term = formal_candidates[0]
                return evidence, matched_term

        for page_number in page_order:
            for chunk in self.document.chunks_for_page(page_number):
                found = _window_support(chunk.text, recovery_terms)
                if found:
                    excerpt, matched_term = found
                    return Evidence(
                        document_id=self.document.document_id,
                        page=page_number,
                        section=section,
                        excerpt=excerpt,
                        chunk_id=chunk.chunk_id,
                    ), matched_term

            page = self.document.page(page_number)
            found = _window_support(page.raw_text, recovery_terms)
            if found:
                excerpt, matched_term = found
                return Evidence(
                    document_id=self.document.document_id,
                    page=page_number,
                    section=section,
                    excerpt=excerpt,
                    chunk_id=None,
                ), matched_term
        return None

    def _resolve_last_issue_as_recovery(
        self,
        ref: EvidenceRef,
        *,
        extractor: str,
        object_type: str,
        object_name: str,
        report: EvidenceValidationReport,
        evidence: Evidence,
        matched_term: str,
    ) -> None:
        # The LLM evidence claim remains auditable, but a deterministic source
        # lookup has rescued it. Reclassify that claim from invalid to valid.
        for idx in range(len(report.issues) - 1, -1, -1):
            issue = report.issues[idx]
            if (
                issue.extractor == extractor
                and issue.object_type == object_type
                and issue.object_name == object_name
                and issue.chunk_id == ref.chunk_id
                and issue.page_number == ref.page_number
                and issue.excerpt == ref.excerpt
            ):
                report.issues.pop(idx)
                break
        report.invalid_claims = max(0, report.invalid_claims - 1)
        report.valid_claims += 1
        report.recovered_claims += 1
        report.recoveries.append(EvidenceRecovery(
            extractor=extractor,
            object_type=object_type,
            object_name=object_name,
            original_chunk_id=ref.chunk_id,
            original_page_number=ref.page_number,
            original_excerpt=ref.excerpt,
            recovered_chunk_id=evidence.chunk_id,
            recovered_page_number=evidence.page,
            recovered_excerpt=evidence.excerpt,
            matched_term=matched_term,
        ))

    def validate_many(
        self,
        refs: Iterable[EvidenceRef],
        *,
        extractor: str,
        object_type: str,
        object_name: str,
        report: EvidenceValidationReport,
        recovery_terms: Sequence[str] | None = None,
        prefer_formal_heading: bool = False,
    ) -> list[Evidence]:
        valid: list[Evidence] = []
        for ref in refs:
            evidence = self.validate_ref(
                ref,
                extractor=extractor,
                object_type=object_type,
                object_name=object_name,
                report=report,
            )
            if evidence is not None:
                valid.append(evidence)
                continue

            recovered = self.find_support(
                recovery_terms,
                preferred_page=ref.page_number,
                section=ref.section,
                prefer_formal_heading=prefer_formal_heading,
            )
            if recovered is not None:
                recovered_evidence, matched_term = recovered
                self._resolve_last_issue_as_recovery(
                    ref,
                    extractor=extractor,
                    object_type=object_type,
                    object_name=object_name,
                    report=report,
                    evidence=recovered_evidence,
                    matched_term=matched_term,
                )
                valid.append(recovered_evidence)
        return valid

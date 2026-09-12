from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from vitaguard_do.ingestion.models import IngestedDocument, TextChunk
from vitaguard_do.taxonomy.loader import TaxonomyRegistry, load_taxonomies


LONG_DOCUMENT_PAGE_THRESHOLD = 25


@dataclass(frozen=True)
class SelectorProfile:
    name: str
    keywords: tuple[str, ...]
    max_chunks: int
    long_max_chunks: int


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold()


def _search_norm(text: str) -> str:
    """Accent/case/punctuation-insensitive text used for alias boundaries."""
    text = _norm(text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _term_occurrences(search_text: str, term: str) -> int:
    term = _search_norm(term)
    if not term:
        return 0
    # Word boundaries matter: `segurado` must not match `seguradora`.
    pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
    return len(re.findall(pattern, search_text))


def _leading_heading_score(line: str, term: str) -> int:
    """Score a term used as a formal plain/numbered heading.

    Supports headings whose definition/title continues on the same line, e.g.
    `2.38. Segurado: ...` or `9.12 Cooperacao do Segurado`.
    """
    line_search = _search_norm(line)
    term_search = _search_norm(term)
    if not line_search or not term_search:
        return 0
    numbered_pattern = rf"^(?:\d+\s+)+{re.escape(term_search)}(?:$|\s+)"
    plain_pattern = rf"^{re.escape(term_search)}(?:$|\s+)"
    if re.match(numbered_pattern, line_search):
        remainder = re.sub(numbered_pattern, "", line_search, count=1).strip()
        return 320 if not remainder else 270
    if re.match(plain_pattern, line_search):
        remainder = re.sub(plain_pattern, "", line_search, count=1).strip()
        return 220 if not remainder else 160
    return 0


PROFILES: dict[str, SelectorProfile] = {
    "core": SelectorProfile(
        name="core",
        max_chunks=3,
        long_max_chunks=14,
        keywords=(
            "seguradora", "tomadora", "segurada", "numero da apolice", "vigencia",
            "moeda", "premio", "limite maximo", "limite agregado", "retroatividade",
            "prazo adicional", "ambito geografico", "jurisdicao", "base de cobertura",
            "franquia", "retencao", "limites e franquias", "processo susep", "versao",
            "territorio", "qualquer lugar do mundo", "leis do brasil", "base de reclamacoes",
        ),
    ),
    "risk": SelectorProfile(
        name="risk",
        max_chunks=4,
        long_max_chunks=22,
        keywords=(
            "coberturas", "cobertura", "side a", "side b", "side c", "entity coverage",
            "custos de defesa", "despesas de defesa", "investigacao", "sublimite",
            "bens e liberdade", "extensoes", "extensao", "exclusoes", "exclusao",
            "franquia", "retencao", "garantia a", "garantia b", "garantia basica",
            "bloqueio", "indisponibilidade", "custos de investigacao", "danos ambientais",
            "exclusao conduta", "reclamacoes e circunstancias anteriores",
        ),
    ),
    "semantic": SelectorProfile(
        name="semantic",
        max_chunks=3,
        long_max_chunks=28,
        keywords=(
            "definicoes", "pessoa segurada", "administrador segurado", "reclamacao", "claim",
            "ato danoso", "ato de gestao", "perda", "subsidiaria", "controlada",
            "condicoes e clausulas", "aviso", "notificacao", "cooperacao", "separabilidade",
            "severability", "alteracao de controle", "mudanca de controle", "run-off", "run off",
            "prioridade de pagamentos", "priority of payments", "alocacao", "antecipacao",
            "consentimento para acordo", "ordem dos pagamentos", "adiantamentos de custos de defesa",
            "perda indenizavel",
        ),
    ),
}


def _looks_like_toc(chunk: TextChunk) -> bool:
    text = _norm(chunk.text)
    if "sumario" in text[:500]:
        return True
    # Dot leaders are a strong signal of a table of contents in native-text PDFs.
    return chunk.text.count("....") >= 4 or chunk.text.count("........") >= 2


def _general_conditions_end_page(document: IngestedDocument) -> int:
    """Find the start of a later 'Section II - Special Conditions' if present.

    v0.5A intentionally validates the main General Conditions first. This keeps
    the first real-document benchmark bounded and avoids mixing optional riders
    with the base wording. The full product will later process all sections.
    """
    for page in document.pages:
        if page.page_number <= 10:
            continue
        prefix = _norm(page.clean_text[:1200])
        if "secao ii" in prefix and "condicoes especiais" in prefix:
            return max(1, page.page_number - 1)
        # AIG e outros cadernos podem iniciar um bloco opcional de Condicoes
        # Particulares em uma nova pagina/capa, sem numeracao de "Secao II".
        # Exigimos o heading logo no inicio para nao confundir mencoes incidentais
        # a "condicoes particulares" dentro das Condicoes Gerais.
        head = _norm(page.clean_text[:320])
        if head.startswith("condicoes particulares") or (
            "d o" in head[:80] and "condicoes particulares" in head[:220]
        ):
            return max(1, page.page_number - 1)
    return document.page_count


def _candidate_chunks(document: IngestedDocument, profile_name: str) -> list[TextChunk]:
    if document.page_count < LONG_DOCUMENT_PAGE_THRESHOLD:
        return list(document.chunks)
    end_page = _general_conditions_end_page(document)
    return [
        c for c in document.chunks
        if c.page_number <= end_page and not _looks_like_toc(c)
    ]


def _keyword_score(chunk: TextChunk, keywords: tuple[str, ...]) -> int:
    text = _norm(chunk.text)
    score = 0
    for keyword in keywords:
        k = _norm(keyword)
        occurrences = text.count(k)
        if occurrences:
            score += 3 + min(occurrences - 1, 4)
    return score


def _alias_score(chunk: TextChunk, aliases: tuple[str, ...], *, mode: str) -> int:
    text = _norm(chunk.text)
    search_text = _search_norm(chunk.text)
    prefix_search = search_text[:1200]
    best = 0
    for alias in aliases:
        k = _norm(alias).strip()
        k_search = _search_norm(alias)
        if not k_search:
            continue
        occurrences = _term_occurrences(search_text, alias)
        if not occurrences:
            continue
        score = 8 + min(occurrences, 6)

        # Formal headings deserve a large boost. The boundary-aware search fixes
        # the AIG `Segurado` vs `Seguradora` collision observed in v0.5B.4.
        if mode == "definition":
            for raw_line in chunk.text.splitlines():
                heading_score = _leading_heading_score(raw_line, alias)
                if heading_score:
                    raw_prefix = raw_line.split(":", 1)[0].strip()
                    uppercase_bonus = 45 if raw_prefix and raw_prefix == raw_prefix.upper() else 0
                    score += 180 + heading_score + uppercase_bonus
                    break
        elif mode == "clause":
            for raw_line in chunk.text.splitlines():
                heading_score = _leading_heading_score(raw_line, alias)
                if heading_score:
                    score += 180 + heading_score
                    break
                line = _norm(raw_line)
                if k in line and "clausula" in line:
                    score += 100
                    break
        elif mode == "risk":
            for raw_line in chunk.text.splitlines():
                heading_score = _leading_heading_score(raw_line, alias)
                if heading_score:
                    score += 180 + heading_score
                    break
                line = _norm(raw_line)
                if k in line and any(word in line for word in ("cobertura", "exclusao", "extensao", "garantia")):
                    score += 90
                    break

        if _term_occurrences(prefix_search, alias):
            score += 12
        best = max(best, score)
    return best


def _core_identity_score(chunk: TextChunk) -> int:
    """Prefer the chunk that formally defines the insurer/legal carrier.

    Many real policy wordings do not state the full legal entity on the cover.
    Instead they define "Seguradora" inside the glossary (AIG GO is one such
    case). This is generic and does not hard-code an insurer name or page.
    """
    text = _norm(chunk.text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    score = 0
    for i, line in enumerate(lines):
        if re.match(r"^(?:\d+(?:\.\d+)*\.?\s+)?seguradora\s*:?[\s]*$", line):
            score = max(score, 420)
            neighborhood = " ".join(lines[i : i + 3])
            if "seguros" in neighborhood:
                score += 120
            if re.search(r"\bs\.?\s*a\.?\b", neighborhood):
                score += 60
    # Also recognize an explicit legal carrier sentence even when the heading
    # was split oddly by PDF text extraction.
    if "refere-se" in text and "seguros" in text and re.search(r"\bs\.?\s*a\.?\b", text):
        score = max(score, 500)
    return score


def _best_for_phrase(chunks: list[TextChunk], phrase: str) -> tuple[int, TextChunk] | None:
    p = _norm(phrase)
    best: tuple[int, TextChunk] | None = None
    for chunk in chunks:
        text = _norm(chunk.text)
        if p not in text:
            continue
        score = 80 + (20 if p in text[:1000] else 0)
        candidate = (score, chunk)
        if best is None or (score, -chunk.page_number) > (best[0], -best[1].page_number):
            best = candidate
    return best


def _select_long_document_chunks(
    document: IngestedDocument,
    profile_name: str,
    *,
    registry: TaxonomyRegistry,
    limit: int,
) -> list[TextChunk]:
    chunks = _candidate_chunks(document, profile_name)
    chosen: dict[str, tuple[int, TextChunk]] = {}

    def add(score: int, chunk: TextChunk) -> None:
        previous = chosen.get(chunk.chunk_id)
        if previous is None or score > previous[0]:
            chosen[chunk.chunk_id] = (score, chunk)

    # Identification lives at the beginning of most policy wordings. Preserve
    # the first two physical pages regardless of generic keyword frequency.
    if profile_name == "core":
        for chunk in chunks:
            if chunk.page_number <= 2:
                add(250 - chunk.page_number, chunk)

        # Reserve a high-priority candidate for the formal legal-carrier
        # definition wherever it appears. This fixes real documents where the
        # full insurer name is only stated later in the glossary.
        for chunk in chunks:
            identity_score = _core_identity_score(chunk)
            if identity_score > 0:
                add(1200 + identity_score, chunk)

        heading_phrases = (
            "clausula 3. objetivo do seguro",
            "clausula 10. vigencia",
            "clausula 25. limite e franquia",
            "clausula 34. lei aplicavel e foro",
            "clausula 36. ambito geografico de cobertura",
        )
        for phrase in heading_phrases:
            hit = _best_for_phrase(chunks, phrase)
            if hit:
                add(hit[0] + 70, hit[1])

        # Fill with keyword-rich chunks, but avoid letting repeated references
        # to "limite" crowd out identification/legal sections.
        ranked = sorted(
            ((_keyword_score(c, PROFILES[profile_name].keywords), c) for c in chunks),
            key=lambda x: (x[0], -x[1].page_number),
            reverse=True,
        )
        for score, chunk in ranked:
            if score > 0:
                add(score, chunk)
            if len(chosen) >= limit * 2:
                break

    elif profile_name == "risk":
        categories = ("coverages", "extensions", "exclusions")
        for item in registry.items:
            if item.category not in categories:
                continue
            aliases = (item.label, *item.aliases)
            best: tuple[int, TextChunk] | None = None
            for chunk in chunks:
                score = _alias_score(chunk, aliases, mode="risk")
                if score <= 0:
                    continue
                if best is None or (score, -chunk.page_number) > (best[0], -best[1].page_number):
                    best = (score, chunk)
            if best:
                add(best[0] + 1000, best[1])

        for phrase in (
            "clausula 4. coberturas",
            "clausula 5. extensoes de cobertura",
            "clausula 7. exclusoes",
        ):
            hit = _best_for_phrase(chunks, phrase)
            if hit:
                add(hit[0] + 100, hit[1])

        ranked = sorted(
            ((_keyword_score(c, PROFILES[profile_name].keywords), c) for c in chunks),
            key=lambda x: (x[0], -x[1].page_number),
            reverse=True,
        )
        for score, chunk in ranked:
            if score > 0:
                add(score, chunk)
            if len(chosen) >= limit * 2:
                break

    elif profile_name == "semantic":
        for item in registry.items:
            if item.category not in {"definitions", "clauses"}:
                continue
            mode = "definition" if item.category == "definitions" else "clause"
            aliases = (item.label, *item.aliases)
            best: tuple[int, TextChunk] | None = None
            for chunk in chunks:
                score = _alias_score(chunk, aliases, mode=mode)
                if score <= 0:
                    continue
                if best is None or (score, -chunk.page_number) > (best[0], -best[1].page_number):
                    best = (score, chunk)
            if best:
                add(best[0] + (5000 if mode == "definition" else 3500), best[1])

        for phrase in (
            "clausula 15. aviso de sinistro",
            "clausula 21. alocacao",
            "clausula 22. prioridade de pagamento de perda",
            "clausula 39. definicoes",
        ):
            hit = _best_for_phrase(chunks, phrase)
            if hit:
                add(hit[0] + 100, hit[1])

        ranked = sorted(
            ((_keyword_score(c, PROFILES[profile_name].keywords), c) for c in chunks),
            key=lambda x: (x[0], -x[1].page_number),
            reverse=True,
        )
        for score, chunk in ranked:
            if score > 0:
                add(score, chunk)
            if len(chosen) >= limit * 2:
                break
    else:
        raise KeyError(profile_name)

    ranked_unique = sorted(
        chosen.values(),
        key=lambda x: (x[0], -x[1].page_number),
        reverse=True,
    )[:limit]
    selected = [chunk for _, chunk in ranked_unique]
    selected.sort(key=lambda c: (c.page_number, c.chunk_index_on_page))
    return selected


def select_chunks(
    document: IngestedDocument,
    profile_name: str,
    *,
    max_chunks: int | None = None,
    registry: TaxonomyRegistry | None = None,
) -> list[TextChunk]:
    if profile_name not in PROFILES:
        raise KeyError(f"unknown selector profile: {profile_name}")
    profile = PROFILES[profile_name]

    if document.page_count >= LONG_DOCUMENT_PAGE_THRESHOLD:
        registry = registry or load_taxonomies()
        limit = max_chunks or profile.long_max_chunks
        return _select_long_document_chunks(
            document,
            profile_name,
            registry=registry,
            limit=limit,
        )

    limit = max_chunks or profile.max_chunks
    scored: list[tuple[int, int, TextChunk]] = []
    for chunk in document.chunks:
        text = _norm(chunk.text)
        score = 0
        for keyword in profile.keywords:
            k = _norm(keyword)
            occurrences = text.count(k)
            if occurrences:
                score += 3 + min(occurrences - 1, 3)

        heading_boosts = {
            "core": ("especificacao", "limites e franquias"),
            "risk": ("2. coberturas", "3. extensoes", "4. exclusoes"),
            "semantic": ("1. definicoes", "5. condicoes e clausulas relevantes"),
        }
        for heading in heading_boosts.get(profile_name, ()):
            if _norm(heading) in text:
                score += 50

        scored.append((score, -chunk.page_number, chunk))

    positives = [entry for entry in scored if entry[0] > 0]
    if not positives:
        return document.chunks[:limit]

    positives.sort(key=lambda x: (x[0], x[1]), reverse=True)
    selected = [entry[2] for entry in positives[:limit]]
    selected.sort(key=lambda c: (c.page_number, c.chunk_index_on_page))
    return selected



def _risk_sub_categories(category: str) -> tuple[str, ...]:
    if category == "coverages_extensions":
        return ("coverages", "extensions")
    if category == "exclusions":
        return ("exclusions",)
    raise KeyError(category)


def _risk_sub_keywords(category: str) -> tuple[str, ...]:
    if category == "coverages_extensions":
        return (
            "cobertura", "coberturas", "garantia", "garantia a", "garantia b",
            "extensao", "extensoes", "bens e liberdade", "bloqueio",
            "indisponibilidade", "investigacao", "custos de investigacao",
            "custos de defesa", "sublimite",
        )
    if category == "exclusions":
        return (
            "exclusao", "exclusoes", "conduta", "fraude", "desonestidade",
            "danos ambientais", "danos corporais", "danos materiais",
            "reclamacoes anteriores", "circunstancias anteriores", "litigio anterior",
            "segurado contra segurado", "servicos profissionais",
        )
    raise KeyError(category)


def select_risk_subchunks(
    document: IngestedDocument,
    category: str,
    *,
    registry: TaxonomyRegistry | None = None,
    max_chunks: int | None = None,
) -> list[TextChunk]:
    """Select smaller long-document risk contexts.

    v0.5B.5 applies the successful semantic split to risk extraction. Formal
    taxonomy headings are reserved before generic keyword filler so exclusions
    on dense pages are not omitted by the LLM or crowded out by extensions.
    """
    categories = _risk_sub_categories(category)
    registry = registry or load_taxonomies()
    if document.page_count < LONG_DOCUMENT_PAGE_THRESHOLD:
        return select_chunks(document, "risk", max_chunks=max_chunks, registry=registry)

    chunks = _candidate_chunks(document, "risk")
    limit = max_chunks or (16 if category == "coverages_extensions" else 14)
    chosen: dict[str, tuple[int, TextChunk]] = {}

    def add(score: int, chunk: TextChunk) -> None:
        prior = chosen.get(chunk.chunk_id)
        if prior is None or score > prior[0]:
            chosen[chunk.chunk_id] = (score, chunk)

    for item in registry.items:
        if item.category not in categories:
            continue
        aliases = (item.label, *item.aliases)
        best: tuple[int, TextChunk] | None = None
        for chunk in chunks:
            score = _alias_score(chunk, aliases, mode="risk")
            if score <= 0:
                continue
            if best is None or (score, -chunk.page_number) > (best[0], -best[1].page_number):
                best = (score, chunk)
        if best:
            # Every taxonomy concept gets a chance to reserve its strongest page.
            add(5000 + best[0], best[1])

    section_phrases = (
        ("coberturas", "garantias", "extensoes de cobertura")
        if category == "coverages_extensions"
        else ("exclusoes", "riscos excluidos")
    )
    for phrase in section_phrases:
        hit = _best_for_phrase(chunks, phrase)
        if hit:
            add(1200 + hit[0], hit[1])

    keywords = _risk_sub_keywords(category)
    ranked = sorted(
        ((_keyword_score(c, keywords), c) for c in chunks),
        key=lambda x: (x[0], -x[1].page_number),
        reverse=True,
    )
    for score, chunk in ranked:
        if score > 0:
            add(score, chunk)
        if len(chosen) >= limit * 2:
            break

    ranked_unique = sorted(
        chosen.values(),
        key=lambda x: (x[0], -x[1].page_number),
        reverse=True,
    )[:limit]
    selected = [chunk for _, chunk in ranked_unique]
    selected.sort(key=lambda c: (c.page_number, c.chunk_index_on_page))
    return selected


def detect_risk_candidates(
    chunks: list[TextChunk],
    category: str,
    *,
    registry: TaxonomyRegistry,
) -> list[str]:
    """Detect strong canonical risk items already visible in selected chunks."""
    categories = _risk_sub_categories(category)
    found: list[str] = []
    for item in registry.items:
        if item.category not in categories:
            continue
        aliases = (item.label, *item.aliases)
        best = max((_alias_score(chunk, aliases, mode="risk") for chunk in chunks), default=0)
        if best >= 180:
            found.append(f"{item.category}:{item.id}")
    return sorted(set(found))


def _semantic_sub_keywords(category: str) -> tuple[str, ...]:
    if category == "definitions":
        return (
            "definicoes", "glossario", "segurado", "pessoa segurada", "reclamacao",
            "ato danoso", "ato de gestao", "perda indenizavel", "perda", "custos de defesa",
            "despesas de defesa", "subsidiaria", "controlada",
        )
    if category == "clauses":
        return (
            "alocacao", "ordem dos pagamentos", "prioridade de pagamentos", "adiantamento",
            "custos de defesa", "aviso de sinistro", "notificacao", "separabilidade",
            "alteracao de controle", "run off", "consentimento para acordo", "cooperacao",
        )
    raise KeyError(category)


def select_semantic_subchunks(
    document: IngestedDocument,
    category: str,
    *,
    registry: TaxonomyRegistry | None = None,
    max_chunks: int | None = None,
) -> list[TextChunk]:
    """Select a compact, category-specific semantic context for long wordings.

    v0.5B.5 keeps definitions and clauses split into independent LLM calls. This keeps
    response JSON smaller and prevents unrelated semantic items from competing
    for the same output budget.
    """
    if category not in {"definitions", "clauses"}:
        raise KeyError(category)
    registry = registry or load_taxonomies()
    if document.page_count < LONG_DOCUMENT_PAGE_THRESHOLD:
        return select_chunks(document, "semantic", max_chunks=max_chunks, registry=registry)

    chunks = _candidate_chunks(document, "semantic")
    limit = max_chunks or (18 if category == "definitions" else 16)
    chosen: dict[str, tuple[int, TextChunk]] = {}

    def add(score: int, chunk: TextChunk) -> None:
        prior = chosen.get(chunk.chunk_id)
        if prior is None or score > prior[0]:
            chosen[chunk.chunk_id] = (score, chunk)

    mode = "definition" if category == "definitions" else "clause"
    for item in registry.items:
        if item.category != category:
            continue
        aliases = (item.label, *item.aliases)
        best: tuple[int, TextChunk] | None = None
        for chunk in chunks:
            score = _alias_score(chunk, aliases, mode=mode)
            if score <= 0:
                continue
            if best is None or (score, -chunk.page_number) > (best[0], -best[1].page_number):
                best = (score, chunk)
        if best:
            # Reserve each canonical definition/clause before generic filler.
            add(5000 + best[0], best[1])

    keywords = _semantic_sub_keywords(category)
    ranked = sorted(
        ((_keyword_score(c, keywords), c) for c in chunks),
        key=lambda x: (x[0], -x[1].page_number),
        reverse=True,
    )
    for score, chunk in ranked:
        if score > 0:
            add(score, chunk)
        if len(chosen) >= limit * 2:
            break

    ranked_unique = sorted(
        chosen.values(),
        key=lambda x: (x[0], -x[1].page_number),
        reverse=True,
    )[:limit]
    selected = [chunk for _, chunk in ranked_unique]
    selected.sort(key=lambda c: (c.page_number, c.chunk_index_on_page))
    return selected


def detect_semantic_candidates(
    chunks: list[TextChunk],
    category: str,
    *,
    registry: TaxonomyRegistry,
) -> list[str]:
    """Detect strong formal taxonomy candidates already visible in selected chunks."""
    if category not in {"definitions", "clauses"}:
        raise KeyError(category)
    mode = "definition" if category == "definitions" else "clause"
    threshold = 180 if category == "definitions" else 95
    found: list[str] = []
    for item in registry.items:
        if item.category != category:
            continue
        aliases = (item.label, *item.aliases)
        if max((_alias_score(chunk, aliases, mode=mode) for chunk in chunks), default=0) >= threshold:
            found.append(item.id)
    return sorted(set(found))

def selected_pages(chunks: list[TextChunk]) -> list[int]:
    return sorted({c.page_number for c in chunks})


def render_chunks_for_prompt(chunks: list[TextChunk]) -> str:
    blocks = []
    for chunk in chunks:
        blocks.append(
            f'<CHUNK id="{chunk.chunk_id}" page="{chunk.page_number}">\n'
            f"{chunk.text}\n"
            f"</CHUNK>"
        )
    return "\n\n".join(blocks)

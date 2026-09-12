from __future__ import annotations

import re
import unicodedata


def _norm(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_geographic_scope(value: str | None) -> str | None:
    text = _norm(value)
    if not text:
        return None
    worldwide_markers = (
        "mundial",
        "mundo inteiro",
        "qualquer lugar do mundo",
        "qualquer parte do mundo",
        "worldwide",
        "world wide",
        "anywhere in the world",
    )
    if any(marker in text for marker in worldwide_markers):
        return "WORLDWIDE"
    if text in {"brasil", "brazil", "territorio nacional"}:
        return "BRAZIL"
    return text.upper().replace(" ", "_")


def canonicalize_jurisdiction(value: str | None) -> str | None:
    text = _norm(value)
    if not text:
        return None
    brazil_markers = (
        "brasil",
        "brazil",
        "republica federativa do brasil",
        "leis do brasil",
        "legislacao brasileira",
        "jurisdicao brasileira",
    )
    if any(marker == text or marker in text for marker in brazil_markers):
        return "BR"
    return text.upper().replace(" ", "_")


def canonicalize_coverage_trigger(value: str | None) -> str | None:
    text = _norm(value)
    if not text:
        return None
    if (
        "reclamacoes com notificacao" in text
        or "reclamacao com notificacao" in text
        or "claims made with notification" in text
        or "claims made notification" in text
    ):
        return "CLAIMS_MADE_WITH_NOTIFICATION"
    if (
        "primeira manifestacao" in text
        or "first manifestation" in text
        or "first discovery" in text
    ):
        return "CLAIMS_MADE_FIRST_MANIFESTATION"
    if "base de reclamacoes" in text or "claims made" in text:
        return "CLAIMS_MADE"
    if "base de ocorrencia" in text or text == "occurrence":
        return "OCCURRENCE"
    return text.upper().replace(" ", "_")


def canonicalize_contractual_field(path: str, value: str | None) -> str | None:
    if path == "contractual_terms.geographic_scope":
        return canonicalize_geographic_scope(value)
    if path == "contractual_terms.jurisdiction":
        return canonicalize_jurisdiction(value)
    if path == "contractual_terms.coverage_trigger":
        return canonicalize_coverage_trigger(value)
    return None

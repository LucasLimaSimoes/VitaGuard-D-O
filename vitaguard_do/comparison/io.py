from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from pydantic import ValidationError

from vitaguard_do.models.schema import PolicyPortfolio, PolicyRecord


_POLICY_REQUIRED_KEYS = {
    "policy_id",
    "source_documents",
    "identification",
    "contractual_terms",
    "extraction",
}


def _extract_policy_payload(raw: Any, *, source: Path) -> Mapping[str, Any]:
    """Return a PolicyRecord-shaped mapping from supported VitaGuard JSON files.

    Extraction pipeline files named ``*.structured.json`` are not bare
    ``PolicyRecord`` objects. They are StructuredExtractionRun envelopes and
    keep the assembled policy under ``policy_json``. Comparison also accepts a
    bare PolicyRecord JSON for future UI/import use.
    """
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"Arquivo estruturado invalido em {source}: esperado objeto JSON."
        )

    # Direct PolicyRecord.
    if _POLICY_REQUIRED_KEYS.issubset(raw.keys()):
        return raw

    # Current and historical extraction-run envelope.
    policy_json = raw.get("policy_json")
    if isinstance(policy_json, Mapping):
        return policy_json

    # Small compatibility allowance for future/exported wrappers.
    for key in ("policy", "policy_record"):
        candidate = raw.get(key)
        if isinstance(candidate, Mapping) and _POLICY_REQUIRED_KEYS.issubset(candidate.keys()):
            return candidate

    available = ", ".join(sorted(str(k) for k in raw.keys())[:15])
    raise ValueError(
        "Formato estruturado VitaGuard nao reconhecido em "
        f"{source}. Esperado PolicyRecord direto ou envelope de extracao "
        f"com 'policy_json'. Chaves encontradas: {available or '<nenhuma>'}"
    )


def load_policy_record(path: str | Path) -> PolicyRecord:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalido em {path}: {exc}") from exc

    payload = _extract_policy_payload(raw, source=path)
    try:
        return PolicyRecord.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            f"O PolicyRecord contido em {path} nao corresponde ao schema atual: {exc}"
        ) from exc


def load_portfolio(paths: Iterable[str | Path]) -> PolicyPortfolio:
    policies = [load_policy_record(path) for path in paths]
    return PolicyPortfolio(policies=policies)

from __future__ import annotations

"""Gemini-safe JSON Schema helpers.

Pydantic can emit validation keywords that the Gemini structured-output subset does not
accept consistently. We keep the full Pydantic schema for local validation and send a
sanitized schema to the API.
"""

from typing import Any

from pydantic import BaseModel


# Supported by the current Gemini JSON-schema subset. We intentionally keep local $defs/$ref
# because they are supported and avoid expanding repeated nested models into very large payloads.
_ALLOWED_KEYS = {
    "$id",
    "$defs",
    "$ref",
    "$anchor",
    "type",
    "format",
    "title",
    "description",
    "enum",
    "items",
    "prefixItems",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "anyOf",
    "oneOf",
    "properties",
    "additionalProperties",
    "required",
    "propertyOrdering",
}


def _sanitize(node: Any, *, in_properties: bool = False, in_defs: bool = False) -> Any:
    if isinstance(node, list):
        return [_sanitize(item) for item in node]

    if not isinstance(node, dict):
        return node

    result: dict[str, Any] = {}
    for key, value in node.items():
        # Keys inside properties/$defs are user/model names, not JSON-schema keywords.
        if in_properties or in_defs:
            result[key] = _sanitize(value)
            continue

        if key == "properties" and isinstance(value, dict):
            result[key] = _sanitize(value, in_properties=True)
            continue

        if key == "$defs" and isinstance(value, dict):
            result[key] = _sanitize(value, in_defs=True)
            continue

        if key == "additionalProperties":
            result[key] = _sanitize(value) if isinstance(value, (dict, list)) else value
            continue

        if key not in _ALLOWED_KEYS:
            # Pydantic examples of deliberately stripped fields: default, minLength,
            # maxLength. They remain enforced by local Pydantic validation after parsing.
            continue

        result[key] = _sanitize(value)

    return result


def gemini_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    safe = _sanitize(raw)
    if safe.get("type") != "object":
        raise ValueError(f"Expected object schema for {model.__name__}.")
    return safe


def schema_diagnostics(model: type[BaseModel]) -> dict[str, Any]:
    import json

    raw = model.model_json_schema()
    safe = gemini_json_schema(model)
    raw_text = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    safe_text = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    return {
        "model": model.__name__,
        "raw_chars": len(raw_text),
        "safe_chars": len(safe_text),
        "removed_chars": len(raw_text) - len(safe_text),
    }

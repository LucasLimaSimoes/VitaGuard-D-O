from __future__ import annotations
import json
from pathlib import Path
from vitaguard_do.models.schema import PolicyRecord


def validate_ground_truth_folder(path: str | Path) -> list[str]:
    path = Path(path)
    validated = []
    for p in sorted(path.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        PolicyRecord.model_validate(data)
        validated.append(p.name)
    return validated

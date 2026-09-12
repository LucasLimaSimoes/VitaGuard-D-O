from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vitaguard_do.comparison.io import load_policy_record


@dataclass(frozen=True)
class DemoAssetSpec:
    key: str
    filename: str


DEMO_ASSETS = (
    DemoAssetSpec("allianz", "allianz_do_condicoes_gerais_2025_12.structured.json"),
    DemoAssetSpec("aig", "aig_do_aiggo.structured.json"),
    DemoAssetSpec("executive_plus", "vitaguard_do_executive_plus.structured.json"),
)


def prepare_demo_assets(root: str | Path) -> tuple[dict[str, Path], dict[str, str | None], dict[str, list[str]]]:
    """Load the immutable demo bundle shipped inside the current release.

    v0.7.2 deliberately has no filesystem dependency on older VitaGuard versions.
    The compatibility-shaped return tuple is retained so the Application Service API
    does not need a breaking change before v0.8.
    """
    root = Path(root).resolve()
    demo_dir = root / "data" / "demo" / "structured"

    files: dict[str, Path] = {}
    bundled_from: dict[str, str | None] = {}
    searched: dict[str, list[str]] = {}

    for spec in DEMO_ASSETS:
        path = (demo_dir / spec.filename).resolve()
        searched[spec.key] = [str(path)]
        if not path.exists():
            continue
        # Fail early if the bundled artifact is malformed/incompatible.
        load_policy_record(path)
        files[spec.key] = path
        bundled_from[spec.key] = "bundled"

    return files, bundled_from, searched

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitaguard_do.real_sources import download_real_source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_id", nargs="?", default="allianz_do_2025_12")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-strict", action="store_true")
    args = parser.parse_args()
    download_real_source(args.source_id, force=args.force, strict=not args.no_strict)


if __name__ == "__main__":
    main()

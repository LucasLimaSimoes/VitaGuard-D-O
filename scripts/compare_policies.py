from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitaguard_do.comparison import compare_portfolio, load_portfolio, save_comparison


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compara 2..N PolicyRecords VitaGuard D&O.")
    parser.add_argument("structured", nargs="+", help="Arquivos *.structured.json")
    parser.add_argument("--output", default=str(ROOT / "outputs" / "comparison" / "portfolio"))
    args, _unknown = parser.parse_known_args(argv)

    portfolio = load_portfolio(args.structured)
    report = compare_portfolio(portfolio)
    json_path, md_path = save_comparison(report, args.output)

    s = report.summary
    print("=== VitaGuard D&O v0.6 - Comparison Engine ===")
    print(f"policies={s.policy_count} | rows={s.row_count} | equal={s.equal} | different={s.different} | only_in_some={s.only_in_some} | all_missing={s.all_missing} | needs_review={s.needs_review}")
    print("JSON:", json_path)
    print("Markdown:", md_path)


if __name__ == "__main__":
    main()

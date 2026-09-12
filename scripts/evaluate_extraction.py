from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitaguard_do.evaluation.ground_truth import evaluate_policy, save_evaluation
from vitaguard_do.extraction.models import StructuredExtractionRun
from vitaguard_do.models.schema import PolicyRecord



def main():
    parser = argparse.ArgumentParser(description="Evaluate v0.4 extraction against synthetic ground truth")
    parser.add_argument("--show-details", action="store_true")
    args = parser.parse_args()

    structured_dir = ROOT / "outputs" / "structured"
    gt_dir = ROOT / "tests" / "ground_truth"
    out_dir = ROOT / "outputs" / "evaluation"

    names = ["vitaguard_do_essencial", "vitaguard_do_executive_plus"]
    reports = []
    for name in names:
        structured_path = structured_dir / f"{name}.structured.json"
        gt_path = gt_dir / f"{name}.json"
        if not structured_path.exists():
            print(f"[SKIP] {name}: execute a extracao estruturada primeiro")
            continue

        run = StructuredExtractionRun.from_json_file(structured_path)
        extracted = PolicyRecord.model_validate(run.policy_json)
        expected = PolicyRecord.model_validate_json(gt_path.read_text(encoding="utf-8"))
        report = evaluate_policy(
            extracted,
            expected,
            policy_name=name,
            evidence_report=run.evidence_report,
        )
        save_evaluation(report, out_dir / f"{name}.evaluation.json")
        reports.append(report)

        print(f"\n=== {name} ===")
        print(f"Campos escalares: {report.scalar_correct}/{report.scalar_total} ({report.scalar_accuracy:.1%})")
        print(f"Financeiros: {report.financial_correct}/{report.financial_total} ({report.financial_accuracy:.1%})")
        print(f"F1 canonico medio: {report.canonical_macro_f1:.1%}")
        print(
            f"Sublimites: {report.nested_sublimit_correct}/{report.nested_sublimit_total} "
            f"({report.nested_sublimit_accuracy:.1%})"
        )
        print(
            f"Evidencias validas: {report.evidence_valid}/{report.evidence_total} "
            f"({report.evidence_validity_rate:.1%})"
        )
        if args.show_details:
            for category, metric in report.canonical_sets.items():
                print(
                    f"  {category}: P={metric.precision:.1%} R={metric.recall:.1%} F1={metric.f1:.1%} "
                    f"missing={metric.missing_ids} extra={metric.extra_ids}"
                )
            for note in report.notes:
                print(f"  NOTE: {note}")

    if reports:
        print("\nArquivos de avaliacao gravados em outputs/evaluation/.")


if __name__ == "__main__":
    main()

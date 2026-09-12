from __future__ import annotations

import argparse
from pathlib import Path
import sys



ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitaguard_do.evaluation.real_gold import evaluate_real_gold
from vitaguard_do.extraction.models import StructuredExtractionRun
from vitaguard_do.models.schema import PolicyRecord


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structured", default=str(ROOT / "outputs" / "real" / "allianz_do_condicoes_gerais_2025_12.structured.json"))
    parser.add_argument("--gold", default=str(ROOT / "tests" / "real_gold" / "allianz_do_2025_12.json"))
    args = parser.parse_args()

    run = StructuredExtractionRun.from_json_file(args.structured)
    policy = PolicyRecord.model_validate(run.policy_json)
    report = evaluate_real_gold(policy, gold_path=args.gold, evidence_report=run.evidence_report)

    print("=== Gold set real Allianz ===")
    print(f"fatos={report.passed_facts}/{report.total_facts} ({report.fact_accuracy:.1%})")
    print(f"paginas de evidencia={report.evidence_page_hits}/{report.evidence_page_checks} ({report.evidence_page_accuracy:.1%})")
    print(f"evidencia deterministica={report.deterministic_evidence_validity:.1%}")
    print(f"reparadas={run.evidence_report.repaired_claims} | recuperadas={run.evidence_report.recovered_claims} | invalidas={run.evidence_report.invalid_claims}")
    for result in report.results:
        marker = "OK" if result.passed else "MISS"
        page = "" if result.evidence_page_ok is None else f" | pagina={'OK' if result.evidence_page_ok else 'MISS'} {result.actual_evidence_pages}"
        print(f"[{marker}] {result.id}: esperado={result.expected!r} atual={result.actual!r}{page}")

    if report.taxonomy_gaps:
        print("\nLacunas de taxonomia observadas (nao sao automaticamente erros):")
        for item in report.taxonomy_gaps:
            print("-", item)


if __name__ == "__main__":
    main()

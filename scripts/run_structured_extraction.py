from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitaguard_do.extraction.pipeline import StructuredExtractionPipeline
from vitaguard_do.extraction.provider import GeminiProvider
from vitaguard_do.ingestion.models import IngestedDocument
from vitaguard_do.ingestion.pdf import ingest_pdf, save_ingested_document



def load_or_ingest(pdf: Path) -> IngestedDocument:
    out = ROOT / "outputs" / "ingestion" / f"{pdf.stem}.ingestion.json"
    if out.exists():
        doc = IngestedDocument.from_json_file(out)
        # Re-ingest if the source file changed.
        from vitaguard_do.ingestion.pdf import sha256_file
        if doc.source_sha256 == sha256_file(pdf):
            return doc
    doc = ingest_pdf(pdf)
    save_ingested_document(doc, out)
    return doc


def print_summary(policy, run):
    print(f"\n[OK] {run.source_name}")
    print(f"  provider/model: {run.provider} / {run.model}")
    print(f"  coverages: {len(policy.coverages)}")
    print(f"  extensions: {len(policy.extensions)}")
    print(f"  exclusions: {len(policy.exclusions)}")
    print(f"  definitions: {len(policy.definitions)}")
    print(f"  clauses: {len(policy.clauses)}")
    print(
        f"  evidence: {run.evidence_report.valid_claims}/{run.evidence_report.total_claims} valid "
        f"({run.evidence_report.validity_rate:.1%})"
    )
    if run.warnings:
        for warning in run.warnings:
            print(f"  [WARN] {warning}")


def main():
    parser = argparse.ArgumentParser(description="VitaGuard D&O v0.4.7 structured extraction")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", type=Path, help="PDF to extract")
    group.add_argument("--all-synthetic", action="store_true", help="Process both synthetic VitaGuard PDFs")
    parser.add_argument("--model", default=os.getenv("VITAGUARD_GEMINI_MODEL", "gemini-3.5-flash-lite"))
    parser.add_argument("--force", action="store_true", help="Ignore structured-output cache")
    args = parser.parse_args()

    provider = GeminiProvider(model=args.model)
    pipeline = StructuredExtractionPipeline(
        provider,
        output_dir=ROOT / "outputs" / "structured",
    )

    if args.all_synthetic:
        pdfs = sorted((ROOT / "data" / "synthetic").glob("*.pdf"))
    else:
        pdfs = [args.pdf.resolve()]

    for pdf in pdfs:
        doc = load_or_ingest(pdf)
        policy, run = pipeline.extract(doc, force=args.force)
        print_summary(policy, run)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vitaguard_do.ingestion import IngestionConfig, ingest_pdf, save_ingested_document


def main():
    parser = argparse.ArgumentParser(description="Ingest one PDF into page text + traceable chunks.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--document-id", default=None)
    parser.add_argument("--max-chunk-chars", type=int, default=3000)
    parser.add_argument("--overlap-chars", type=int, default=250)
    parser.add_argument("--keep-marginal-lines", action="store_true")
    args = parser.parse_args()

    config = IngestionConfig(
        max_chunk_chars=args.max_chunk_chars,
        overlap_chars=args.overlap_chars,
        remove_repeated_marginal_lines=not args.keep_marginal_lines,
    )
    doc = ingest_pdf(args.pdf, document_id=args.document_id, config=config)

    output = args.output or (ROOT / "outputs" / "ingestion" / f"{args.pdf.stem}.ingestion.json")
    save_ingested_document(doc, output)

    print(f"[OK] {args.pdf.name}")
    print(f"     document_id: {doc.document_id}")
    print(f"     pages: {doc.page_count}")
    print(f"     native/low/empty: {doc.stats.native_text_pages}/{doc.stats.low_text_pages}/{doc.stats.empty_pages}")
    print(f"     clean chars: {doc.stats.total_clean_chars}")
    print(f"     chunks: {doc.stats.chunk_count}")
    print(f"     repeated marginal lines: {doc.stats.repeated_marginal_lines_detected}")
    print(f"     output: {output}")


if __name__ == "__main__":
    main()

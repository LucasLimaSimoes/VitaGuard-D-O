from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vitaguard_do.comparison.models import ComparisonReport, ComparisonStatus, ComparisonValue, HarmonizedPresenceStatus


STATUS_PT = {
    ComparisonStatus.EQUAL: "IGUAL",
    ComparisonStatus.DIFFERENT: "DIFERENTE",
    ComparisonStatus.ONLY_IN_SOME: "IDENTIFICADO SÓ EM ALGUMAS",
    ComparisonStatus.ALL_MISSING: "AUSENTE EM TODAS",
    ComparisonStatus.NEEDS_REVIEW: "REVISAR",
}


HARMONIZED_STATUS_PT = {
    HarmonizedPresenceStatus.PRESENT_IN_ALL: "IDENTIFICADA EM TODAS",
    HarmonizedPresenceStatus.PRESENT_IN_SOME: "IDENTIFICADA EM ALGUMAS",
    HarmonizedPresenceStatus.ABSENT_IN_ALL: "NÃO IDENTIFICADA",
    HarmonizedPresenceStatus.NEEDS_REVIEW: "REVISAR",
}


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _short(text: str, max_chars: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _value_display(value: ComparisonValue) -> str:
    if not value.present:
        status = value.extraction_status.value if value.extraction_status else "NOT_FOUND"
        return f"— ({status})"

    raw = value.value
    if value.source_name:
        base = value.source_name
    elif isinstance(raw, str):
        base = raw
    elif isinstance(raw, dict):
        if "raw_text" in raw:
            base = str(raw["raw_text"])
        elif "start" in raw or "end" in raw:
            base = f"{raw.get('start') or '?'} → {raw.get('end') or '?'}"
        else:
            base = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    elif isinstance(raw, list):
        base = f"{len(raw)} ocorrência(s)"
    else:
        base = str(raw)

    pages = sorted({ev.page for ev in value.evidence})
    page_text = f" [p.{','.join(str(x) for x in pages)}]" if pages else ""
    return _short(base) + page_text


_MATERIAL_SECTION_PRIORITY = {
    "coverages": 0,
    "extensions": 1,
    "exclusions": 2,
    "clauses": 3,
    "policy_limits": 4,
    "policy_deductibles": 5,
    "contractual_terms": 6,
    "definitions": 7,
}

_STATUS_PRIORITY = {
    ComparisonStatus.NEEDS_REVIEW: 0,
    ComparisonStatus.ONLY_IN_SOME: 1,
    ComparisonStatus.DIFFERENT: 2,
}


def select_key_differences(report: ComparisonReport, *, limit: int = 12):
    """Return a deterministic shortlist of materially useful differences.

    Identification metadata (insurer/product/SUSEP) is intentionally excluded:
    it helps identify the documents but is not itself a coverage difference.
    """
    candidates = [
        row for row in report.rows
        if row.section in _MATERIAL_SECTION_PRIORITY
        and row.status in _STATUS_PRIORITY
    ]
    candidates.sort(
        key=lambda row: (
            _MATERIAL_SECTION_PRIORITY[row.section],
            _STATUS_PRIORITY[row.status],
            row.label.casefold(),
            row.field_id,
        )
    )
    return candidates[: max(0, limit)]


def _status_display(row) -> str:
    if row.status == ComparisonStatus.ONLY_IN_SOME:
        return f"IDENTIFICADO EM {row.present_count}/{row.policy_count}"
    return STATUS_PT[row.status]


def _key_difference_line(row) -> str:
    values = "; ".join(
        f"{value.policy_label}: {_value_display(value)}" for value in row.values
    )
    return f"- **{row.label}** — {_status_display(row)} — {values}"


def render_markdown(report: ComparisonReport) -> str:
    s = report.summary
    lines = [
        "# VitaGuard D&O — Comparação determinística",
        "",
        f"Apólices: **{s.policy_count}** | Linhas: **{s.row_count}** | "
        f"Iguais: **{s.equal}** | Diferentes: **{s.different}** | "
        f"Identificado só em algumas: **{s.only_in_some}** | Revisar: **{s.needs_review}**",
        "",
        "## Apólices",
        "",
    ]
    for policy_id in report.policy_ids:
        lines.append(f"- `{policy_id}` — {report.policy_labels[policy_id]}")

    if report.harmonized_concepts:
        lines.extend([
            "",
            "## Visão harmonizada por família",
            "",
            "> Esta visão agrupa conceitos relacionados que podem aparecer em seções diferentes. Ela indica presença semântica no portfólio, **não equivalência contratual** entre cláusulas/coberturas.",
            "",
        ])
        for concept in report.harmonized_concepts:
            present = ", ".join(
                value.policy_label for value in concept.values if value.present
            ) or "nenhuma apólice"
            lines.append(
                f"- **{concept.label}** — {HARMONIZED_STATUS_PT[concept.status]} "
                f"({concept.presence_fraction}) — presença: {present}"
            )
            lines.append(f"  - {concept.description}")

    key_rows = select_key_differences(report, limit=12)
    lines.extend([
        "",
        "## Principais diferenças",
        "",
        "> Priorização determinística para navegação. Não representa recomendação de melhor apólice.",
        "",
    ])
    if key_rows:
        lines.extend(_key_difference_line(row) for row in key_rows)
    else:
        lines.append("Nenhuma diferença material priorizável foi identificada.")

    review_rows = [row for row in report.rows if row.status == ComparisonStatus.NEEDS_REVIEW]
    if review_rows:
        lines.extend(["", "## Itens para revisão", ""] )
        for row in review_rows:
            lines.append(f"- **{row.label}**")
            for note in row.notes[1:] if len(row.notes) > 1 else row.notes:
                lines.append(f"  - {note}")

    sections: dict[str, list] = {}
    for row in report.rows:
        sections.setdefault(row.section, []).append(row)

    for section, rows in sections.items():
        lines.extend(["", f"## {section}", ""])
        headers = ["Campo / conceito", *[report.policy_labels[p] for p in report.policy_ids], "Resultado"]
        lines.append("| " + " | ".join(_escape(h) for h in headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            cells = [row.label]
            by_id = {v.policy_id: v for v in row.values}
            cells.extend(_value_display(by_id[p]) for p in report.policy_ids)
            cells.append(_status_display(row))
            lines.append("| " + " | ".join(_escape(str(c)) for c in cells) + " |")

    lines.extend([
        "",
        "## Observações",
        "",
        "- O alinhamento usa IDs canônicos e valores normalizados; o texto original e as evidências permanecem no JSON.",
        "- `DIFERENTE` não significa automaticamente que uma apólice é melhor: significa apenas que os valores estruturados relevantes não são iguais.",
        "- `IDENTIFICADO EM X/N` significa que o conceito apareceu no `PolicyRecord` de X das N apólices. Isso **não comprova ausência jurídica** nas demais; pode refletir escopo documental ou de extração.",
        "- `REVISAR` é usado quando a comparação encontrou ambiguidade, conflito ou duplicidade para a mesma chave comparativa.",
        "- Para limites e franquias, a chave comparativa considera `canonical_id + applies_to`; retenções de Side A, Side B e Side C são linhas distintas.",
        "- A visão harmonizada por família serve para navegação semântica entre estruturas editoriais diferentes e não substitui a comparação estrutural detalhada.",
    ])
    return "\n".join(lines) + "\n"


def save_comparison(report: ComparisonReport, output_base: str | Path) -> tuple[Path, Path]:
    base = Path(output_base)
    base.parent.mkdir(parents=True, exist_ok=True)
    json_path = base.with_suffix(".comparison.json")
    md_path = base.with_suffix(".comparison.md")
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path

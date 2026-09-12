from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitaguard_do import __version__
from vitaguard_do.application import (
    AskVitaGuardResult,
    DemoDataUnavailableError,
    SUGGESTED_QUESTIONS,
    VitaGuardApplicationService,
)
from vitaguard_do.comparison import ComparisonStatus, HarmonizedPresenceStatus, render_markdown


STATUS_PT = {
    ComparisonStatus.EQUAL: "Igual",
    ComparisonStatus.DIFFERENT: "Diferente",
    ComparisonStatus.ONLY_IN_SOME: "Presença parcial",
    ComparisonStatus.ALL_MISSING: "Não identificado",
    ComparisonStatus.NEEDS_REVIEW: "Revisar",
}

STATUS_ICON = {
    ComparisonStatus.EQUAL: "🟢",
    ComparisonStatus.DIFFERENT: "🟠",
    ComparisonStatus.ONLY_IN_SOME: "🔵",
    ComparisonStatus.ALL_MISSING: "⚪",
    ComparisonStatus.NEEDS_REVIEW: "🟣",
}

EXTRACTION_STATUS_PT = {
    "FOUND": "Identificado",
    "NOT_FOUND": "Não identificado",
    "AMBIGUOUS": "Ambíguo",
    "NOT_APPLICABLE": "Não aplicável",
    "CONFLICTING": "Conflitante",
}

SECTION_PT = {
    "identification": "Identificação",
    "contractual_terms": "Termos contratuais",
    "policy_limits": "Limites",
    "policy_deductibles": "Franquias",
    "coverages": "Coberturas",
    "extensions": "Extensões",
    "exclusions": "Exclusões",
    "definitions": "Definições",
    "clauses": "Cláusulas",
}


def _is_synthetic_overview(overview) -> bool:
    # Only the bundled demo record is tagged as synthetic at source level.
    # A user may upload the synthetic fixture in live mode; that upload must remain
    # labelled by its own source/job rather than inheriting demo-only presentation.
    origin = str(getattr(overview, "document_origin", "") or "").casefold()
    return origin == "synthetic_vitaguard"


def _looks_synthetic_policy_label(label: str) -> bool:
    value = str(label or "").casefold()
    return "vitaguard" in value and "fict" in value


def _policy_short_label(overview) -> str:
    insurer = (overview.insurer or "").strip()
    product = (overview.product or "").strip()
    insurer_lower = insurer.casefold()
    if "allianz" in insurer_lower:
        return "Allianz"
    if "aig" in insurer_lower:
        return "AIG"
    if "vitaguard" in insurer_lower:
        if "executive plus" in product.casefold():
            label = "VitaGuard Executive Plus"
        else:
            label = "VitaGuard"
        if _is_synthetic_overview(overview):
            label += " · Sintética"
        return label
    if insurer and insurer != "Não identificado":
        return insurer[:32]
    return product[:32] if product else "Apólice"


def _source_suffix(source_file: str) -> str:
    stem = Path(source_file or "").stem
    stem = re.sub(r"(?i)^vitaguard[_\- ]*do[_\- ]*", "", stem)
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem:
        return "Documento"
    return stem.title()


def _unique_policy_labels(overviews) -> dict[str, str]:
    base_labels = [_policy_short_label(p) for p in overviews]
    counts = {}
    for label in base_labels:
        counts[label] = counts.get(label, 0) + 1

    labels = {}
    used = set()
    for p, base in zip(overviews, base_labels):
        label = base
        if counts[base] > 1:
            label = f"{base} · {_source_suffix(p.source_file)}"
        candidate = label
        n = 2
        while candidate in used:
            candidate = f"{label} ({n})"
            n += 1
        labels[p.policy_id] = candidate
        used.add(candidate)
    return labels


def _friendly_extraction_status(value) -> str:
    if not value.extraction_status:
        return "Não identificado"
    raw = value.extraction_status.value
    return EXTRACTION_STATUS_PT.get(raw, raw.replace("_", " ").title())


def _format_date(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    text = str(value)
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return text


def _format_structured_value(raw) -> str:
    if raw is None:
        return "Não identificado"
    if isinstance(raw, (date, datetime)):
        return _format_date(raw)
    if isinstance(raw, dict):
        # Intervalos de vigência / datas.
        if raw.get("start") or raw.get("end"):
            start = _format_date(raw.get("start")) if raw.get("start") else "?"
            end = _format_date(raw.get("end")) if raw.get("end") else "?"
            return f"{start} a {end}"
        # Itens financeiros alinhados guardam o valor dentro de `value`.
        nested = raw.get("value")
        if isinstance(nested, dict):
            return _format_structured_value(nested)
        # Valores normalizados preservam a forma legível original quando disponível.
        if raw.get("raw_text"):
            return str(raw["raw_text"])
        if raw.get("normalized_text"):
            return str(raw["normalized_text"])
        # Fallback útil para estruturas simples; evita JSON bruto na interface.
        parts = []
        for key, val in raw.items():
            if val in (None, [], {}, ""):
                continue
            if key in {"kind", "currency", "unit", "numeric_value"}:
                parts.append(str(val))
        if parts:
            return " · ".join(parts)
        return "Dados estruturados disponíveis"
    if isinstance(raw, list):
        return f"{len(raw)} ocorrência(s)"
    return str(raw)


def _value_text(value) -> str:
    if not value.present:
        return _friendly_extraction_status(value)

    raw = value.value
    # Financeiros e escalares estruturados devem exibir o valor, não o nome interno do item.
    if isinstance(raw, dict) and (
        "value" in raw or "raw_text" in raw or "normalized_text" in raw or "start" in raw or "end" in raw
    ):
        return _format_structured_value(raw)
    if isinstance(raw, (date, datetime)):
        return _format_structured_value(raw)

    # Para coberturas/extensões/cláusulas, o nome de origem é o melhor resumo de célula.
    if value.source_name:
        return value.source_name
    return _format_structured_value(raw)


def _compact_text(text: str, max_chars: int = 56) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "…"


def _family_presence_map(report) -> dict[str, str]:
    return {
        concept.comparison_concept_id: concept.presence_fraction
        for concept in report.harmonized_concepts
        if concept.status != HarmonizedPresenceStatus.ABSENT_IN_ALL
    }


def _result_text(row, family_presence: str | None = None) -> str:
    if row.status == ComparisonStatus.ONLY_IN_SOME:
        text = f"{STATUS_ICON[row.status]} Presente em {row.present_count} de {row.policy_count}"
        if row.comparison_concept_id and family_presence and family_presence != row.presence_fraction:
            text += f" · família {family_presence}"
        return text
    return f"{STATUS_ICON[row.status]} {STATUS_PT[row.status]}"


def _row_table(report, rows, short_labels: dict[str, str], *, compact: bool = True):
    data = []
    family_presence = _family_presence_map(report)
    for row in rows:
        item = {
            "Seção": SECTION_PT.get(row.section, row.section),
            "Campo / conceito": row.label,
            "Resultado": _result_text(row, family_presence.get(row.comparison_concept_id or "")),
        }
        by_id = {v.policy_id: v for v in row.values}
        for pid in report.policy_ids:
            value_text = _value_text(by_id[pid])
            item[short_labels.get(pid, report.policy_labels[pid])] = (
                _compact_text(value_text) if compact else value_text
            )
        data.append(item)
    return data


def _table_column_config(st, short_labels: dict[str, str]):
    config = {
        "Seção": st.column_config.TextColumn("Seção", width="small"),
        "Campo / conceito": st.column_config.TextColumn("Campo / conceito", width="medium"),
        "Resultado": st.column_config.TextColumn("Resultado", width="medium"),
    }
    for label in short_labels.values():
        config[label] = st.column_config.TextColumn(label, width="medium")
    return config


def _render_evidence(st, row):
    st.subheader(row.label)
    st.caption(
        f"{SECTION_PT.get(row.section, row.section)} · {row.field_id} · presença {row.presence_fraction}"
    )
    for value in row.values:
        with st.expander(value.policy_label, expanded=False):
            st.write("**Valor estruturado:**", _value_text(value))
            if value.extraction_status:
                st.write("**Status de extração:**", _friendly_extraction_status(value))
            if value.notes:
                st.write("**Observação:**", value.notes)
            if not value.evidence:
                st.caption("Nenhuma evidência associada a este valor.")
                continue
            for idx, ev in enumerate(value.evidence, start=1):
                st.markdown(f"**Evidência {idx} — página {ev.page}**")
                if ev.section:
                    st.caption(ev.section)
                st.code(ev.excerpt, language=None)
                meta = f"document_id={ev.document_id}"
                if ev.chunk_id:
                    meta += f" · chunk_id={ev.chunk_id}"
                st.caption(meta)


def _render_harmonized_cards(st, report, short_labels: dict[str, str]):
    st.subheader("Famílias harmonizadas")
    st.caption(
        "Agrupamento semântico para navegação. As famílias não declaram equivalência contratual."
    )
    concepts = list(report.harmonized_concepts)
    if not concepts:
        st.info("Nenhuma família harmonizada disponível para esta seleção.")
        return

    columns = st.columns(min(2, len(concepts)))
    for idx, concept in enumerate(concepts):
        status = {
            HarmonizedPresenceStatus.PRESENT_IN_ALL: "Presente em todas",
            HarmonizedPresenceStatus.PRESENT_IN_SOME: "Presente em algumas",
            HarmonizedPresenceStatus.ABSENT_IN_ALL: "Não identificada",
            HarmonizedPresenceStatus.NEEDS_REVIEW: "Revisar",
        }[concept.status]
        with columns[idx % len(columns)].container(border=True):
            st.markdown(f"**{concept.label}**")
            st.markdown(f"### {concept.presence_fraction} · {status}")
            with st.expander("Entender esta família"):
                st.caption(concept.description)
                st.markdown("**Composição por apólice**")
                for policy_id in report.policy_ids:
                    matches = next(
                        (x for x in concept.values if x.policy_id == policy_id),
                        None,
                    )
                    label = short_labels.get(policy_id, report.policy_labels[policy_id])
                    if matches and matches.present:
                        st.write(f"✅ **{label}:** {', '.join(matches.matched_members)}")
                    else:
                        st.write(f"— **{label}:** não identificado nesta família")



def _assistant_scope_token(scope_id: str) -> str:
    import hashlib

    return hashlib.sha256(scope_id.encode("utf-8", errors="replace")).hexdigest()[:12]


def _render_assistant_evidence(st, ev):
    with st.container(border=True):
        st.markdown(f"**[{ev.evidence_id}] {ev.policy_label}**")
        if _looks_synthetic_policy_label(ev.policy_label):
            st.caption("🧪 Demonstração sintética · não representa seguradora ou produto comercial real.")
        meta = f"{ev.field_label} · página {ev.page}"
        if ev.section:
            meta += f" · {ev.section}"
        st.caption(meta)
        excerpt = " ".join(str(ev.excerpt).split())
        st.markdown(f"> {excerpt}")


def _assistant_badges_html(result: AskVitaGuardResult) -> str:
    evidence_count = len(result.evidence)
    return f"""
    <div class="vg-answer-badges">
      <span class="vg-pill vg-pill-green">✓ Contexto recuperado</span>
      <span class="vg-pill">📎 {evidence_count} evidência{'s' if evidence_count != 1 else ''}</span>
      <span class="vg-pill">⚙ Comparação determinística</span>
    </div>
    """


def _render_assistant_result(st, result: AskVitaGuardResult, *, feedback_key: str | None = None, review_count: int = 0):
    st.markdown(result.answer_markdown)
    st.markdown(_assistant_badges_html(result), unsafe_allow_html=True)

    if review_count:
        st.caption(
            f"👤 A comparação atual contém {review_count} item(ns) para revisão humana. "
            "O assistente não resolve ambiguidades estruturais por conta própria."
        )

    if result.caveats:
        with st.expander("⚠️ Ressalvas desta resposta"):
            for item in result.caveats:
                st.write("•", item)

    if result.evidence:
        primary = result.evidence[:3]
        with st.expander(f"📎 Evidências principais ({len(primary)})"):
            for ev in primary:
                _render_assistant_evidence(st, ev)
        if len(result.evidence) > len(primary):
            with st.expander(f"Ver todas as evidências ({len(result.evidence)})"):
                for ev in result.evidence:
                    _render_assistant_evidence(st, ev)

    with st.expander("🧭 Como esta resposta foi construída"):
        st.markdown(
            "O **Ask VitaGuard** recebe apenas o contexto recuperado da comparação atual. "
            "O LLM redige a explicação, mas não altera os resultados do Comparison Engine."
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Linhas recuperadas", result.rows_considered)
        c2.metric("Famílias", result.harmonized_concepts_considered)
        c3.metric("Glossário", result.glossary_items_considered)
        c4.metric("Evidências validadas", len(result.evidence))
        st.caption(f"Modelo de geração: {result.model}")
        st.caption(
            "Referências são validadas localmente; IDs inexistentes no contexto são descartados. "
            "A autoridade final permanece nos dados estruturados e nas evidências."
        )

    if feedback_key:
        st.caption("Esta resposta foi útil?")
        feedback = st.feedback("thumbs", key=feedback_key)
        if feedback is not None:
            st.caption("Obrigado pelo feedback — ele ajuda a avaliar a experiência do assistente nesta sessão.")


def _chat_end_marker(st, token: str):
    st.markdown(f'<div id="vg-chat-end-{token}" class="vg-chat-end"></div>', unsafe_allow_html=True)


def _scroll_chat_to_end(st, token: str, *, force: bool = False):
    pending_key = f"vg_ask_scroll_pending_{token}"
    if not force and not st.session_state.pop(pending_key, False):
        return
    try:
        import streamlit.components.v1 as components
        marker_id = f"vg-chat-end-{token}"
        components.html(
            f"""
            <script>
            (() => {{
              const scrollNow = () => {{
                const marker = window.parent.document.getElementById('{marker_id}');
                if (marker) marker.scrollIntoView({{behavior: 'smooth', block: 'end'}});
              }};
              setTimeout(scrollNow, 90);
              setTimeout(scrollNow, 320);
            }})();
            </script>
            """,
            height=0,
            width=0,
        )
    except Exception:
        # Auto-scroll is a UX enhancement; chat must remain functional if browser internals change.
        pass


def _render_suggested_questions(st, token: str, *, compact: bool = False):
    pending_question = None
    if compact:
        holder = st.expander("💡 Perguntas sugeridas")
    else:
        holder = st.container()
        st.markdown("**Não sabe por onde começar?**")
    with holder:
        suggestion_cols = st.columns(2)
        for idx, question in enumerate(SUGGESTED_QUESTIONS):
            if suggestion_cols[idx % 2].button(
                question,
                key=f"vg_ask_suggestion_{token}_{idx}",
                use_container_width=True,
            ):
                pending_question = question
    return pending_question


def _render_ask_tab(st, service, report, *, api_key: str | None, scope_id: str):
    import os

    st.markdown(
        """
        <div class="vg-assistant-hero">
          <div class="vg-assistant-icon">✦</div>
          <div>
            <div class="vg-assistant-title">Ask VitaGuard</div>
            <div class="vg-assistant-sub">Converse com a comparação em linguagem simples, com evidências rastreáveis.</div>
          </div>
        </div>
        <div class="vg-answer-badges vg-assistant-controls">
          <span class="vg-pill vg-pill-green">Contexto fundamentado</span>
          <span class="vg-pill">Evidências por página</span>
          <span class="vg-pill">Guardrails locais</span>
          <span class="vg-pill">Revisão humana</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Como o VitaGuard controla as respostas?"):
        st.markdown(
            """
            1. **Recupera** apenas os conceitos, famílias, glossário e evidências relevantes para a pergunta.
            2. **Gera** a explicação com Gemini sem permitir que o modelo reclassifique a comparação.
            3. **Verifica** as referências citadas contra a lista real de evidências enviada ao modelo.
            4. **Escala para revisão humana** quando há ambiguidade, conflito ou contexto insuficiente.

            `Não identificado` não significa ausência jurídica, e famílias harmonizadas não significam equivalência contratual.
            """
        )

    token = _assistant_scope_token(scope_id)
    history_key = f"vg_ask_history_{token}"
    input_key = f"vg_ask_input_{token}"
    key_key = f"vg_ask_api_key_{token}"
    processing_key = f"vg_ask_processing_{token}"
    cache_key = f"vg_ask_cache_{token}"
    history = st.session_state.setdefault(history_key, [])
    answer_cache = st.session_state.setdefault(cache_key, {})

    env_key_available = bool(os.getenv("GEMINI_API_KEY"))
    assistant_key = api_key
    if assistant_key:
        st.caption("Gemini conectado pela chave desta análise · chave mantida somente em memória.")
    elif env_key_available:
        st.caption("Gemini conectado por `GEMINI_API_KEY` do ambiente.")
    else:
        with st.expander("🔐 Conectar Gemini", expanded=not bool(history)):
            assistant_key = st.text_input(
                "Gemini API key para o Ask VitaGuard",
                type="password",
                key=key_key,
                help="Usada apenas para gerar respostas nesta sessão; não é gravada pelo VitaGuard.",
            )
            st.caption("A chave permanece somente em memória durante a sessão atual.")

    pending_question = _render_suggested_questions(st, token, compact=bool(history))

    top_left, top_right = st.columns([5, 1])
    top_left.caption("Histórico temporário desta sessão · sem persistência do conteúdo do chat.")
    if top_right.button("Nova conversa", key=f"vg_ask_clear_{token}", use_container_width=True):
        st.session_state[history_key] = []
        st.session_state.pop(processing_key, None)
        st.session_state.pop(f"vg_ask_scroll_pending_{token}", None)
        st.rerun()

    for idx, message in enumerate(history):
        role = message.get("role", "assistant")
        with st.chat_message(role):
            if role == "assistant" and message.get("result"):
                try:
                    result = AskVitaGuardResult.model_validate(message["result"])
                    _render_assistant_result(
                        st,
                        result,
                        feedback_key=f"vg_ask_feedback_{token}_{idx}",
                        review_count=report.summary.needs_review,
                    )
                except Exception:
                    st.markdown(message.get("content", "Resposta indisponível."))
            else:
                st.markdown(message.get("content", ""))

    processing_question = st.session_state.get(processing_key)
    if processing_question:
        try:
            normalized_cache_key = " ".join(processing_question.casefold().split())
            cached_payload = answer_cache.get(normalized_cache_key)
            with st.chat_message("assistant"):
                if cached_payload is not None:
                    result = AskVitaGuardResult.model_validate(cached_payload)
                else:
                    with st.spinner("Consultando a comparação e as evidências..."):
                        result = service.ask(report, processing_question, api_key=assistant_key)
                    answer_cache[normalized_cache_key] = result.model_dump(mode="json")
                _render_assistant_result(
                    st,
                    result,
                    feedback_key=f"vg_ask_feedback_{token}_{len(history)}",
                    review_count=report.summary.needs_review,
                )
            history.append({"role": "assistant", "result": result.model_dump(mode="json")})
        except ValueError as exc:
            message = str(exc)
            history.append({"role": "assistant", "content": message})
            with st.chat_message("assistant"):
                st.warning(message)
        except Exception as exc:
            message = "Não foi possível gerar a resposta agora. Verifique a chave/cota Gemini e tente novamente."
            history.append({"role": "assistant", "content": message})
            st.session_state[f"vg_ask_last_error_{token}"] = f"{type(exc).__name__}: {exc}"
            with st.chat_message("assistant"):
                st.warning(message)
        finally:
            st.session_state.pop(processing_key, None)
            st.session_state[f"vg_ask_scroll_pending_{token}"] = True
        # Re-render the completed turn so the composer returns below the newest answer.
        st.rerun()

    typed_question = st.chat_input(
        "Pergunte sobre coberturas, diferenças, termos ou itens para revisão...",
        key=input_key,
    )
    _chat_end_marker(st, token)
    _scroll_chat_to_end(st, token)

    question = pending_question or typed_question
    if not question:
        return

    question = " ".join(question.split()).strip()
    if not assistant_key and not env_key_available and not service.can_answer_locally(report, question):
        st.warning("Esta pergunta precisa do Gemini. Informe uma API key para continuar. As perguntas sugeridas mais comuns podem ser respondidas localmente.")
        return

    history.append({"role": "user", "content": question})
    st.session_state[processing_key] = question
    st.session_state[f"vg_ask_scroll_pending_{token}"] = True
    # State-machine rerun keeps the composer at the end instead of above the generated reply.
    st.rerun()

def _render_dashboard(st, service, policies, report, short_labels: dict[str, str], *, live_bundle=None, assistant_api_key=None, assistant_scope_id=None):
    s = report.summary

    if live_bundle is not None:
        st.success(
            f"Análise viva concluída: {len(live_bundle.documents)} documento(s) · "
            f"modelo {live_bundle.model}."
        )

    tab_overview, tab_compare, tab_evidence, tab_review, tab_ask, tab_about = st.tabs(
        ["Visão geral", "Comparação", "Evidências", "Revisões", "Ask VitaGuard", "Sobre"]
    )

    with tab_overview:
        cols = st.columns(6)
        cols[0].metric("Apólices", s.policy_count)
        cols[1].metric("Conceitos", s.row_count)
        cols[2].metric("Iguais", s.equal)
        cols[3].metric("Diferentes", s.different)
        cols[4].metric("Presença parcial", s.only_in_some)
        cols[5].metric("Revisar", s.needs_review)

        st.subheader("Apólices carregadas")
        by_overview_id = {p.policy_id: p for p in policies}
        live_by_policy = (
            {item.policy_id: item for item in live_bundle.documents}
            if live_bundle is not None else {}
        )
        for pid in report.policy_ids:
            overview = by_overview_id[pid]
            with st.expander(short_labels[pid], expanded=False):
                st.caption(overview.product)
                if _is_synthetic_overview(overview):
                    st.info("🧪 **Demonstração sintética** — apólice fictícia criada para testes e comparação do MVP.")
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Seguradora:** {overview.insurer}")
                c1.write(f"**Arquivo:** {overview.source_file}")
                c2.write(f"**Coberturas:** {overview.coverage_count}")
                c2.write(f"**Extensões:** {overview.extension_count}")
                c3.write(f"**Exclusões:** {overview.exclusion_count}")
                c3.write(f"**Definições:** {overview.definition_count}")

                if live_bundle is not None:
                    stages = service.processing_stages_live(overview.policy_id)
                    artifact = live_by_policy.get(pid)
                    if artifact:
                        source_label = "PDF" if artifact.source_kind == "PDF" else "Imagem"
                        st.caption(
                            f"{source_label}: {artifact.page_count} página(s) · "
                            f"texto nativo em {artifact.native_text_pages} · "
                            f"multimodal em {artifact.multimodal_text_pages} · "
                            f"páginas com pouco/nenhum texto: {artifact.low_text_pages + artifact.empty_pages}"
                        )
                        if artifact.warnings:
                            st.warning(" · ".join(artifact.warnings))
                else:
                    stages = service.processing_stages(overview.policy_id)

                st.write("**Status do processamento**")
                stage_cols = st.columns(len(stages))
                for idx, stage in enumerate(stages):
                    mark = "✅" if stage.completed else "⚠️"
                    detail = f"\n{stage.detail}" if stage.detail else ""
                    stage_cols[idx].caption(f"{mark} {stage.label}{detail}")

        _render_harmonized_cards(st, report, short_labels)

    with tab_compare:
        st.subheader("Principais diferenças")
        st.caption(
            "Priorização determinística para navegação; não representa recomendação de melhor apólice."
        )
        key_rows = service.key_differences(report, limit=10)
        st.dataframe(
            _row_table(report, key_rows, short_labels, compact=True),
            use_container_width=True,
            hide_index=True,
            column_config=_table_column_config(st, {pid: short_labels[pid] for pid in report.policy_ids}),
        )
        if any(row.comparison_concept_id for row in key_rows):
            st.caption(
                "Quando o resultado também mostra “família X/N”, a ocorrência estrutural está em parte do portfólio, "
                "mas uma proteção relacionada foi identificada nas demais apólices. Isso não implica equivalência contratual."
            )

        with st.expander("Ver valores completos das principais diferenças"):
            family_presence = _family_presence_map(report)
            for row in key_rows:
                st.markdown(
                    f"**{_result_text(row, family_presence.get(row.comparison_concept_id or ''))} · {row.label}**"
                )
                cols = st.columns(len(row.values))
                for idx, value in enumerate(row.values):
                    label = short_labels.get(value.policy_id, value.policy_label)
                    cols[idx].caption(label)
                    cols[idx].write(_value_text(value))
                st.divider()

        with st.expander("Abrir matriz técnica completa", expanded=False):
            st.caption(
                "Camada de auditoria. Use os filtros para inspecionar todos os conceitos estruturados e seus valores por apólice."
            )
            status_options = [
                ComparisonStatus.DIFFERENT,
                ComparisonStatus.ONLY_IN_SOME,
                ComparisonStatus.NEEDS_REVIEW,
                ComparisonStatus.EQUAL,
                ComparisonStatus.ALL_MISSING,
            ]
            chosen_statuses = st.multiselect(
                "Filtrar por resultado",
                options=status_options,
                default=[
                    ComparisonStatus.DIFFERENT,
                    ComparisonStatus.ONLY_IN_SOME,
                    ComparisonStatus.NEEDS_REVIEW,
                ],
                format_func=lambda x: f"{STATUS_ICON[x]} {STATUS_PT[x]}",
            )
            section_options = list(dict.fromkeys(row.section for row in report.rows))
            chosen_sections = st.multiselect(
                "Filtrar por seção",
                options=section_options,
                default=section_options,
                format_func=lambda x: SECTION_PT.get(x, x),
            )
            compact_mode = st.toggle(
                "Textos compactos na matriz",
                value=True,
                help="Desative para exibir o texto estruturado completo nas células.",
            )
            filtered = [
                r
                for r in report.rows
                if r.status in chosen_statuses and r.section in chosen_sections
            ]
            st.caption(
                f"{len(filtered)} linha(s) exibida(s) de {len(report.rows)}. "
                "A tabela aceita rolagem horizontal quando necessário."
            )
            st.dataframe(
                _row_table(report, filtered, short_labels, compact=compact_mode),
                use_container_width=True,
                height=min(680, 42 + max(1, min(len(filtered), 15)) * 35),
                hide_index=True,
                column_config=_table_column_config(st, {pid: short_labels[pid] for pid in report.policy_ids}),
            )

        d1, d2 = st.columns(2)
        md = render_markdown(report)
        d1.download_button(
            "Baixar relatório comparativo (.md)",
            data=md.encode("utf-8"),
            file_name="vitaguard_comparison.md",
            mime="text/markdown",
            use_container_width=True,
        )
        d2.download_button(
            "Baixar dados comparativos (.json)",
            data=report.model_dump_json(indent=2).encode("utf-8"),
            file_name="vitaguard_comparison.json",
            mime="application/json",
            use_container_width=True,
        )

    with tab_evidence:
        st.subheader("Explorador de evidências")
        st.caption(
            "Selecione um conceito para inspecionar valor, status e trecho de origem por apólice."
        )
        evidence_rows = [r for r in report.rows if any(v.evidence for v in r.values)]
        if not evidence_rows:
            st.info("Nenhuma evidência estruturada disponível nesta seleção.")
        else:
            options = [(r.section, r.field_id) for r in evidence_rows]
            selected_key = st.selectbox(
                "Campo / conceito",
                options=options,
                format_func=lambda key: next(
                    f"{SECTION_PT.get(r.section, r.section)} · {r.label}"
                    for r in evidence_rows
                    if (r.section, r.field_id) == key
                ),
            )
            row = next(r for r in evidence_rows if (r.section, r.field_id) == selected_key)
            _render_evidence(st, row)

    with tab_review:
        reviews = service.review_items(report)
        st.subheader(f"Itens para revisão ({len(reviews)})")
        if not reviews:
            st.success("Nenhum item requer revisão nesta seleção.")
        for item in reviews:
            with st.expander(f"🟣 {item.label} · {item.presence_fraction}", expanded=True):
                st.caption(f"{SECTION_PT.get(item.section, item.section)} · {item.field_id}")
                for note in item.notes:
                    st.write("•", note)
        st.info(
            "Revisar significa que o sistema encontrou ocorrências ambíguas ou concorrentes e se recusou a escolher silenciosamente entre elas."
        )

    with tab_ask:
        scope_id = assistant_scope_id or ("comparison:" + ",".join(report.policy_ids))
        _render_ask_tab(
            st,
            service,
            report,
            api_key=assistant_api_key,
            scope_id=scope_id,
        )

    with tab_about:
        st.subheader("Sobre esta versão")
        st.markdown(
            """
            **A v1.0 mantém respostas frequentes instantâneas e usa contexto compacto nas perguntas livres.** O mesmo
            `VitaGuardApplicationService` recebe documentos enviados pelo usuário, aproveita texto nativo
            quando disponível e usa leitura multimodal Gemini como fallback para páginas escaneadas e imagens.
            Depois executa a extração semântica, monta `PolicyRecord`s e entrega os registros ao Comparison Engine 2..N.

            O modo Demonstração continua disponível com os três resultados previamente auditados.
            O modo **Analisar documentos** é o caminho end-to-end real.

            **Princípios mantidos:**
            - LLM para extração semântica e explicação em linguagem natural;
            - Python determinístico para validação e comparação;
            - evidência rastreável por documento/página/trecho;
            - ausência estruturada não é tratada automaticamente como ausência jurídica;
            - famílias harmonizadas não afirmam equivalência contratual;
            - IDs internos são convertidos em rótulos humanos antes de chegar ao usuário;
            - referências do Ask VitaGuard são verificadas localmente;
            - ambiguidade permanece sujeita a revisão humana;
            - a chave Gemini digitada na interface não é gravada pelo VitaGuard em arquivo.

            **Entrada suportada nesta etapa:** PDF com texto nativo, PDF escaneado e imagens PNG/JPG/JPEG/WEBP.
            Páginas com pouco ou nenhum texto nativo são renderizadas e lidas pelo Gemini multimodal antes da
            extração estruturada. A transcrição multimodal é cacheada por job para evitar repetir chamadas. O **Ask VitaGuard** usa somente a comparação atual, o glossário e evidências selecionadas para responder em linguagem simples, sem alterar o resultado determinístico.
            """
        )
        with st.expander("Controles de IA e rastreabilidade"):
            st.markdown(
                """
                O desenho desta interface aplica conceitos trabalhados no curso: **contexto recuperado com fontes**, 
                **verificação externa ao LLM**, **observabilidade**, **feedback do usuário**, **transparência** e 
                **supervisão humana proporcional ao risco**. O assistente mostra como a resposta foi construída e 
                mantém as evidências disponíveis para auditoria.
                """
            )

        with st.expander("Dados de demonstração"):
            st.write(
                "Allianz, AIG e Executive Plus são carregadas de `data/demo/structured/` "
                "dentro desta própria versão. Nenhuma pasta VitaGuard anterior é necessária."
            )
        if live_bundle is not None:
            with st.expander("Execução viva atual"):
                st.write(f"**Job:** `{live_bundle.job_id}`")
                st.write(f"**Modelo:** {live_bundle.model}")
                st.write(f"**Documentos:** {len(live_bundle.documents)}")
                st.caption("Caches de transcrição multimodal e de extração ficam em outputs/live/ para permitir retomada se uma chamada falhar.")


def _uploaded_job_id(uploaded_files) -> str | None:
    if not uploaded_files:
        return None
    import hashlib

    h = hashlib.sha256()
    for item in uploaded_files:
        payload = item.getvalue()
        h.update(item.name.encode("utf-8", errors="replace"))
        h.update(b"\0")
        h.update(payload)
        h.update(b"\0")
    return h.hexdigest()[:16]


def main():
    import os
    import streamlit as st

    st.set_page_config(page_title="VitaGuard D&O", page_icon="🛡️", layout="wide")
    st.markdown(
        """
        <style>
        :root {
          --vg-blue: #2563eb;
          --vg-cyan: #0891b2;
          --vg-green: #059669;
          --vg-border: rgba(100,116,139,.22);
          --vg-soft: rgba(37,99,235,.055);
          --vg-soft-2: rgba(8,145,178,.055);
          --vg-shadow: 0 10px 28px rgba(15,23,42,.055);
        }
        .block-container {padding-top: 2.65rem; padding-bottom: 4rem; max-width: 1500px;}
        .vg-hero {
          padding: 1.2rem 1.35rem 1.05rem;
          border: 1px solid var(--vg-border);
          border-radius: 18px;
          margin-bottom: .9rem;
          background: linear-gradient(135deg, var(--vg-soft), var(--vg-soft-2));
          box-shadow: var(--vg-shadow);
        }
        .vg-kicker {font-size: .75rem; text-transform: uppercase; letter-spacing: .11em; opacity: .67; font-weight: 650;}
        .vg-title {font-size: 2.08rem; font-weight: 780; margin: .13rem 0 .2rem; letter-spacing: -.025em;}
        .vg-sub {opacity: .77; margin: 0 0 .72rem; max-width: 850px;}
        .vg-hero-chips, .vg-answer-badges {display:flex; flex-wrap:wrap; gap:.42rem; align-items:center;}
        .vg-pill {
          display:inline-flex; align-items:center; gap:.28rem;
          border:1px solid rgba(100,116,139,.24);
          border-radius:999px; padding:.28rem .58rem;
          font-size:.76rem; line-height:1.1; opacity:.88;
          background:rgba(148,163,184,.075);
        }
        .vg-pill-green {border-color:rgba(5,150,105,.24); background:rgba(5,150,105,.08);}
        .vg-assistant-hero {
          display:flex; align-items:center; gap:.85rem;
          padding:1rem 1.05rem; margin:.15rem 0 .65rem;
          border:1px solid var(--vg-border); border-radius:16px;
          background:linear-gradient(135deg, rgba(37,99,235,.07), rgba(8,145,178,.055));
        }
        .vg-assistant-icon {
          width:2.55rem; height:2.55rem; border-radius:13px;
          display:flex; align-items:center; justify-content:center;
          font-size:1.35rem; color:#fff;
          background:linear-gradient(135deg, var(--vg-blue), var(--vg-cyan));
          box-shadow:0 8px 18px rgba(37,99,235,.18);
        }
        .vg-assistant-title {font-size:1.34rem; font-weight:760; letter-spacing:-.015em;}
        .vg-assistant-sub {font-size:.91rem; opacity:.72; margin-top:.06rem;}
        .vg-assistant-controls {margin:0 0 .85rem .1rem;}
        .vg-chat-end {height:1px; margin-top:.2rem;}

        [data-testid="stMetric"] {
          border:1px solid var(--vg-border);
          border-radius:14px;
          padding:.72rem .86rem;
          background:rgba(148,163,184,.045);
          box-shadow:0 4px 14px rgba(15,23,42,.025);
        }
        [data-testid="stMetricLabel"] {opacity:.72;}
        [data-testid="stExpander"] {border-radius:12px !important; overflow:hidden;}
        [data-testid="stAlert"] {border-radius:13px;}
        [data-testid="stChatMessage"] {
          border:1px solid rgba(100,116,139,.18);
          border-radius:16px;
          padding:.55rem .75rem;
          margin-bottom:.68rem;
          background:rgba(148,163,184,.035);
        }
        [data-testid="stChatInput"] {border-radius:16px;}
        [data-baseweb="tab-list"] {gap:.12rem;}
        [data-baseweb="tab"] {border-radius:9px 9px 0 0; padding-left:.8rem; padding-right:.8rem;}
        [data-baseweb="tab"][aria-selected="true"] {font-weight:700;}
        .stButton > button, .stDownloadButton > button {border-radius:10px;}

        [data-testid="stToolbar"] {display: none !important;}
        [data-testid="stDecoration"] {display: none !important;}
        header[data-testid="stHeader"] {background: transparent !important;}
        #MainMenu {visibility: hidden !important;}
        footer {visibility: hidden !important;}
        [data-testid="stDataFrame"] {overflow-x: auto; border-radius:12px;}
        [data-testid="stSidebar"] > div:first-child {border-right:1px solid rgba(100,116,139,.12);}
        [data-testid="stSidebar"] [data-baseweb="tag"] {max-width: 100%; border-radius:8px;}
        [data-testid="stSidebar"] [data-baseweb="tag"] > span {overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""<div class="vg-hero"><div class="vg-kicker">InsurMinds · Projeto Final · v{__version__}</div>
        <div class="vg-title">VitaGuard D&O</div>
        <p class="vg-sub">Análise inteligente de apólices D&O, comparação 2..N e explicações fundamentadas em evidências.</p>
        <div class="vg-hero-chips">
          <span class="vg-pill">📄 PDF + imagem</span>
          <span class="vg-pill">⇄ Comparação 2..N</span>
          <span class="vg-pill">📎 Evidências rastreáveis</span>
          <span class="vg-pill vg-pill-green">✦ Ask VitaGuard</span>
        </div></div>""",
        unsafe_allow_html=True,
    )

    service = VitaGuardApplicationService(ROOT)

    with st.sidebar:
        st.header("VitaGuard")
        mode = st.radio("Modo atual", ["Demonstração", "Analisar documentos"])

    if mode == "Demonstração":
        try:
            service.prepare_demo()
            policies = service.list_demo_policies()
        except DemoDataUnavailableError as exc:
            st.error("Não foi possível preparar o modo Demonstração.")
            st.code(str(exc), language=None)
            return
        except Exception as exc:
            st.exception(exc)
            return

        all_ids = [p.policy_id for p in policies]
        short_labels = {p.policy_id: _policy_short_label(p) for p in policies}
        with st.sidebar:
            st.divider()
            selected = st.multiselect(
                "Apólices na comparação",
                options=all_ids,
                default=all_ids,
                format_func=lambda pid: short_labels[pid],
            )
            if len(selected) < 2:
                st.warning("Selecione pelo menos duas apólices.")
                return
            st.caption("Comparação determinística: o LLM não decide igualdade ou diferença.")
            if any(_is_synthetic_overview(p) and p.policy_id in selected for p in policies):
                st.caption("🧪 A VitaGuard Executive Plus é uma demonstração sintética.")

        report = service.compare_demo(selected)
        _render_dashboard(
            st, service, policies, report, short_labels,
            assistant_scope_id="demo:" + ",".join(sorted(selected)),
        )
        return

    # --------------------------- modo vivo v1.0 ---------------------------
    from vitaguard_do.application import (
        LiveAnalysisBundle,
        LiveInputError,
        MultimodalTextUnavailableError,
        NativeTextUnavailableError,
    )

    st.subheader("Analisar novos documentos")
    st.caption(
        "Envie pelo menos duas apólices D&O em PDF ou imagem. O VitaGuard aproveita texto nativo quando existe, "
        "usa Gemini multimodal em páginas escaneadas/imagens, estrutura os dados, valida evidências e executa "
        "a mesma comparação determinística do modo Demonstração."
    )
    st.info(
        "Formatos aceitos: PDF, PNG, JPG/JPEG e WEBP. Em PDFs mistos, somente as páginas com pouco ou nenhum "
        "texto nativo usam o fallback multimodal. PDFs escaneados extensos podem consumir mais tempo e cota Gemini."
    )

    env_key_available = bool(os.getenv("GEMINI_API_KEY"))
    if env_key_available:
        st.success("GEMINI_API_KEY detectada no ambiente. A chave não será exibida.")
        api_key = None
    else:
        api_key = st.text_input(
            "Gemini API key",
            type="password",
            help="Usada somente em memória durante esta sessão; o VitaGuard não grava a chave nos arquivos do job.",
            key="vg_gemini_key",
        )

    uploaded = st.file_uploader(
        "Apólices D&O em PDF ou imagem",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        help="Para comparar, envie 2 ou mais documentos. Imagens são tratadas como documentos de uma página.",
    )
    current_job_id = _uploaded_job_id(uploaded)

    bundle = None
    raw_bundle = st.session_state.get("vg_live_bundle")
    if raw_bundle:
        try:
            bundle = LiveAnalysisBundle.model_validate(raw_bundle)
        except Exception:
            st.session_state.pop("vg_live_bundle", None)
            bundle = None

    b1, b2 = st.columns([1, 1])
    process_disabled = not uploaded or len(uploaded) < 2 or (not env_key_available and not api_key)
    process_clicked = b1.button(
        "Processar e comparar",
        type="primary",
        disabled=process_disabled,
        use_container_width=True,
    )
    if bundle is not None:
        if b2.button("Limpar análise atual", use_container_width=True):
            try:
                service.clear_live(bundle)
            except Exception:
                pass
            st.session_state.pop("vg_live_bundle", None)
            st.session_state.pop("vg_live_selected", None)
            st.session_state.pop("vg_live_selected_job_id", None)
            st.rerun()

    if uploaded and len(uploaded) < 2:
        st.info("Envie pelo menos dois documentos para executar a comparação.")
    if uploaded and len(uploaded) > 5:
        st.warning("Para a demonstração, recomendamos no máximo 5 documentos por execução.")

    if process_clicked:
        file_specs = [(item.name, item.getvalue()) for item in uploaded]
        try:
            job_id, job_dir, paths = service.prepare_live_uploads(file_specs)
            with st.status("Preparando análise...", expanded=True) as status:
                def progress(event: str, message: str):
                    status.write(message)

                live_bundle = service.analyze_live(
                    job_id=job_id,
                    job_dir=job_dir,
                    paths=paths,
                    api_key=api_key,
                    progress=progress,
                )
                status.update(label="Análise concluída", state="complete", expanded=False)
            st.session_state["vg_live_bundle"] = live_bundle.model_dump(mode="json")
            st.rerun()
        except (LiveInputError, NativeTextUnavailableError, MultimodalTextUnavailableError, ValueError) as exc:
            st.error(str(exc))
            st.info("Se algumas etapas Gemini já haviam concluído, os caches foram preservados. Corrija o problema e tente novamente.")
            return
        except Exception as exc:
            st.error("O processamento vivo falhou.")
            st.exception(exc)
            st.info(
                "Os estágios concluídos ficam em cache dentro de `outputs/live/`. "
                "Uma nova tentativa com os mesmos documentos reaproveita o trabalho salvo."
            )
            return

    if bundle is None:
        st.info("Após o processamento, a comparação aparecerá aqui usando a mesma interface validada no modo Demonstração.")
        return

    if current_job_id and current_job_id != bundle.job_id:
        st.session_state.pop("vg_live_selected", None)
        st.session_state.pop("vg_live_selected_job_id", None)
        st.warning(
            "Os documentos selecionados agora são diferentes da análise anterior. "
            "Clique em **Processar e comparar** para atualizar os resultados."
        )
        return

    try:
        policies = service.list_live_policies(bundle)
    except Exception as exc:
        st.error("Não foi possível reabrir os resultados da análise viva.")
        st.exception(exc)
        return

    all_ids = [p.policy_id for p in policies]
    short_labels = _unique_policy_labels(policies)

    if st.session_state.get("vg_live_selected_job_id") != bundle.job_id:
        st.session_state.pop("vg_live_selected", None)
        st.session_state["vg_live_selected_job_id"] = bundle.job_id

    with st.sidebar:
        st.divider()
        selected = st.multiselect(
            "Apólices na comparação",
            options=all_ids,
            default=all_ids,
            format_func=lambda pid: short_labels[pid],
            key="vg_live_selected",
        )
        if len(selected) < 2:
            st.warning("Selecione pelo menos duas apólices.")
            return
        st.caption("Comparação determinística: o LLM extrai; Python decide igualdade/diferença.")

    try:
        report = service.compare_live(bundle, selected)
    except (ValueError, KeyError) as exc:
        st.warning(str(exc))
        st.info("Atualize a seleção e mantenha pelo menos duas apólices válidas na comparação.")
        return
    except Exception:
        st.error("Não foi possível atualizar a comparação desta análise.")
        st.info("Tente limpar a análise atual e processar novamente os documentos.")
        return

    _render_dashboard(
        st, service, policies, report, short_labels,
        live_bundle=bundle,
        assistant_api_key=api_key,
        assistant_scope_id="live:" + bundle.job_id + ":" + ",".join(sorted(selected)),
    )


if __name__ == "__main__":
    main()

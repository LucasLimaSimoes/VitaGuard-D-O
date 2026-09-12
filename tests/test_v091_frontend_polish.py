from pathlib import Path

from vitaguard_do.application import VitaGuardApplicationService, humanize_internal_identifiers
from vitaguard_do.application.assistant import AssistantAnswerPayload

ROOT = Path(__file__).resolve().parents[1]


class _LeakyProvider:
    def __init__(self, api_key=None):
        self.model = "fake-leaky-provider"

    def generate_structured(self, prompt, schema):
        assert schema is AssistantAnswerPayload
        assert "NUNCA exponha IDs internos/canônicos" in prompt
        assert "Em resumo" in prompt
        return schema(
            answer_markdown=(
                "**Em resumo:** revise [allocation] e `priority_of_payments`; "
                "a evidência principal é [E1]."
            ),
            evidence_ids=["E1"],
            caveats=[],
        )


def _report():
    service = VitaGuardApplicationService(ROOT)
    service.prepare_demo()
    return service, service.compare_demo()


def test_humanizer_replaces_internal_ids_but_preserves_evidence_markers():
    _, report = _report()
    result = humanize_internal_identifiers(
        "Veja [allocation], `priority_of_payments` e [E12].",
        report,
    )
    assert "[allocation]" not in result
    assert "priority_of_payments" not in result
    assert "Aloc" in result
    assert "Prioridade" in result
    assert "[E12]" in result


def test_service_postprocesses_leaky_llm_answer():
    service, report = _report()
    result = service.ask(
        report,
        "O que devo observar?",
        api_key="test-key",
        provider_factory=_LeakyProvider,
    )
    assert "[allocation]" not in result.answer_markdown
    assert "priority_of_payments" not in result.answer_markdown
    assert "[E1]" in result.answer_markdown


def test_streamlit_chat_has_auto_scroll_and_compact_evidence():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "_scroll_chat_to_end" in source
    assert "scrollIntoView" in source
    assert "vg-chat-end" in source
    assert "Evidências principais" in source
    assert "Ver todas as evidências" in source


def test_streamlit_chat_exposes_transparency_human_review_and_feedback():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Como esta resposta foi construída" in source
    assert "revisão humana" in source.lower()
    assert 'st.feedback("thumbs"' in source
    assert "Contexto fundamentado" in source
    assert "Guardrails locais" in source


def test_frontend_has_polished_project_hero():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "InsurMinds · Projeto Final" in source
    assert "vg-hero-chips" in source
    assert "Ask VitaGuard" in source

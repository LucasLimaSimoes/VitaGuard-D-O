from pathlib import Path

from vitaguard_do.application import VitaGuardApplicationService, build_assistant_context
from vitaguard_do.application.assistant import AssistantAnswerPayload


ROOT = Path(__file__).resolve().parents[1]


class _FakeAssistantProvider:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.model = "fake-ask-vitagard"
        self.prompt = None

    def generate_structured(self, prompt, schema):
        self.prompt = prompt
        assert schema is AssistantAnswerPayload
        assert "Comparison Engine determinístico" in prompt
        assert "Não identificado" in prompt
        return schema(
            answer_markdown="Side A protege diretamente a pessoa segurada quando aplicável [E1].",
            evidence_ids=["E1", "E999"],
            caveats=["A extensão exata depende do contrato analisado."],
        )


def _report():
    service = VitaGuardApplicationService(ROOT)
    service.prepare_demo()
    return service, service.compare_demo()


def test_assistant_context_is_grounded_and_retrieves_side_a():
    _, report = _report()
    context = build_assistant_context(report, "O que significa Side A? Explique de forma simples.")

    assert context.rows_count >= 1
    assert context.glossary_count >= 1
    assert context.evidence
    assert "Cobertura direta aos administradores (Side A)" in context.prompt
    assert '"field_id"' not in context.prompt
    assert "Protecao direta a pessoas seguradas" in context.prompt
    assert "NÃO significa automaticamente" in context.prompt


def test_service_ask_filters_unknown_evidence_ids():
    service, report = _report()
    result = service.ask(
        report,
        "A Side A tem alguma diferença material entre Allianz e AIG?",
        api_key="test-key",
        provider_factory=_FakeAssistantProvider,
    )

    assert result.model == "fake-ask-vitagard"
    assert result.evidence
    assert [item.evidence_id for item in result.evidence] == ["E1"]
    assert any("descartadas" in item for item in result.caveats)
    assert result.rows_considered >= 1


def test_assistant_context_review_question_includes_review_row():
    _, report = _report()
    context = build_assistant_context(report, "Existe algum item que exige revisão humana?")
    assert '"status":"NEEDS_REVIEW"' in context.prompt
    assert "Subsidiaria" in context.prompt or "Subsidiária" in context.prompt


def test_streamlit_exposes_ask_vitagard_tab_and_suggestions():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert '"Ask VitaGuard"' in source
    assert "SUGGESTED_QUESTIONS" in source
    assert "st.chat_input" in source
    assert "Evidências principais" in source

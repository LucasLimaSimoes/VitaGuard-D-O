from pathlib import Path

from vitaguard_do.application import VitaGuardApplicationService
from vitaguard_do.application.assistant import AssistantAnswerPayload, build_assistant_context

ROOT = Path(__file__).resolve().parents[1]


class _MustNotRunProvider:
    def __init__(self, api_key=None):
        raise AssertionError("Provider não deveria ser criado para fast path local")


class _CountingProvider:
    calls = 0

    def __init__(self, api_key=None):
        self.model = "fake-counting-provider"

    def generate_structured(self, prompt, schema):
        type(self).calls += 1
        assert schema is AssistantAnswerPayload
        return schema(
            answer_markdown="**Em resumo:** resposta gerada com contexto compacto.",
            evidence_ids=[],
            caveats=[],
        )


def _service_report():
    service = VitaGuardApplicationService(ROOT)
    service.prepare_demo()
    return service, service.compare_demo()


def test_all_suggested_questions_use_local_fast_path_without_provider():
    service, report = _service_report()
    questions = [
        "Resuma as principais diferenças entre as apólices.",
        "O que significa Side A? Explique de forma simples.",
        "Quais proteções aparecem em todas as apólices?",
        "O que foi identificado apenas em algumas apólices?",
        "Há algum item que exige revisão humana?",
        "Pode me recomendar qual seguro contratar?",
    ]
    for question in questions:
        assert service.can_answer_locally(report, question)
        result = service.ask(
            report,
            question,
            api_key=None,
            provider_factory=_MustNotRunProvider,
        )
        assert result.model.startswith("VitaGuard local")
        assert result.answer_markdown


def test_free_form_question_still_uses_gemini_provider_path():
    service, report = _service_report()
    _CountingProvider.calls = 0
    question = "Eu não entendo muito de seguros. O que deveria observar primeiro nessa comparação?"
    assert not service.can_answer_locally(report, question)
    result = service.ask(
        report,
        question,
        api_key="test-key",
        provider_factory=_CountingProvider,
    )
    assert _CountingProvider.calls == 1
    assert result.model == "fake-counting-provider"


def test_free_form_context_is_compact_and_bounded():
    _, report = _service_report()
    context = build_assistant_context(
        report,
        "Eu não entendo muito de seguros. O que deveria observar primeiro nessa comparação?",
    )
    assert context.rows_count <= 7
    assert len(context.evidence) <= 12
    assert len(context.prompt) < 25000
    assert '"field_id"' not in context.prompt
    assert '"comparison_concept_id"' not in context.prompt


def test_recommendation_fast_path_is_neutral_and_instant():
    service, report = _service_report()
    result = service.ask(
        report,
        "Me recomende uma das seguradoras",
        provider_factory=_MustNotRunProvider,
    )
    text = result.answer_markdown.casefold()
    assert "não posso indicar" in text
    assert "coberturas" in text
    assert "exclusões" in text
    assert "franquias" in text


def test_frontend_has_session_answer_cache_and_local_key_bypass():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "vg_ask_cache_" in source
    assert "answer_cache.get" in source
    assert "service.can_answer_locally(report, question)" in source
    assert "Esta pergunta precisa do Gemini" in source

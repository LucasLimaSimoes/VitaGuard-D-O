from pathlib import Path

from vitaguard_do.application import (
    VitaGuardApplicationService,
    mark_synthetic_policy_mentions,
    reinforce_recommendation_guardrail,
    strip_internal_rule_references,
)
from vitaguard_do.application.assistant import AssistantAnswerPayload

ROOT = Path(__file__).resolve().parents[1]


class _RuleLeakProvider:
    def __init__(self, api_key=None):
        self.model = "fake-rule-leak-provider"

    def generate_structured(self, prompt, schema):
        assert schema is AssistantAnswerPayload
        assert "NUNCA mencione números de regras" in prompt
        assert "demonstração sintética" in prompt
        return schema(
            answer_markdown=(
                "**Em resumo:** Não posso recomendar uma contratação [Regra 9]. "
                "A VitaGuard Executive Plus pode ser comparada pelos critérios disponíveis [Regras 1, 13]."
            ),
            evidence_ids=[],
            caveats=[],
        )


def _service_report():
    service = VitaGuardApplicationService(ROOT)
    service.prepare_demo()
    return service, service.compare_demo()


def test_rule_reference_sanitizer_removes_harness_rules_but_preserves_evidence():
    text = "Compare [E1]. Bloqueado por [Regra 9] e (Regras 1, 13). Isto ocorre por Regra 10, mas siga."
    cleaned = strip_internal_rule_references(text)
    assert "[E1]" in cleaned
    assert "Regra 9" not in cleaned
    assert "Regras 1, 13" not in cleaned
    assert "Regra 10" not in cleaned
    assert "por," not in cleaned


def test_recommendation_guardrail_offers_neutral_criteria():
    text = reinforce_recommendation_guardrail(
        "Não posso indicar qual seguradora você deve contratar.",
        "Me recomende uma das seguradoras",
    )
    assert "não posso indicar" in text.casefold()
    assert "diga sua prioridade" in text.casefold()
    assert "coberturas" in text.casefold()
    assert "franquias" in text.casefold()


def test_synthetic_policy_is_marked_on_first_assistant_mention():
    _, report = _service_report()
    text = mark_synthetic_policy_mentions(
        "A VitaGuard Executive Plus possui este item no exemplo.",
        report,
    )
    assert "demonstração sintética" in text.casefold()


def test_service_removes_rule_leaks_and_marks_synthetic_policy():
    service, report = _service_report()
    result = service.ask(
        report,
        "Compare a estrutura de alocação da VitaGuard Executive Plus com as demais apólices.",
        api_key="test-key",
        provider_factory=_RuleLeakProvider,
    )
    assert "Regra 9" not in result.answer_markdown
    assert "Regras 1, 13" not in result.answer_markdown
    assert "demonstração sintética" in result.answer_markdown.casefold()


def test_frontend_labels_synthetic_demo_and_uses_new_conversation():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "VitaGuard Executive Plus · Sintética" not in source  # built dynamically
    assert 'label += " · Sintética"' in source
    assert "🧪 **Demonstração sintética**" in source
    assert 'button("Nova conversa"' in source
    assert 'button("Limpar chat"' not in source

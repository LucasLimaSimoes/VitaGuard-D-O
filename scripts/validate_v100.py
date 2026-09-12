from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vitaguard_do import __version__
from vitaguard_do.application import VitaGuardApplicationService
from vitaguard_do.application.assistant import build_assistant_context


class _MustNotRunProvider:
    def __init__(self, api_key=None):
        raise AssertionError("Gemini/provider não deveria ser criado no fast path local")


def main():
    print("=== VitaGuard D&O v1.0.0 - validação de release ===")
    assert __version__ == "1.0.0", __version__

    service = VitaGuardApplicationService(ROOT)
    service.prepare_demo()
    report = service.compare_demo()
    assert len(report.policy_ids) >= 2
    assert report.rows

    fast_questions = [
        "Resuma as principais diferenças entre as apólices.",
        "O que significa Side A? Explique de forma simples.",
        "Quais proteções aparecem em todas as apólices?",
        "O que foi identificado apenas em algumas apólices?",
        "Há algum item que exige revisão humana?",
        "Pode me recomendar qual seguro contratar?",
    ]
    for question in fast_questions:
        assert service.can_answer_locally(report, question)
        result = service.ask(report, question, provider_factory=_MustNotRunProvider)
        assert result.answer_markdown.strip()
        assert result.model.startswith("VitaGuard local")

    free_form = "Eu não entendo muito de seguros. O que deveria observar primeiro nessa comparação?"
    context = build_assistant_context(report, free_form)
    assert context.rows_count <= 7
    assert len(context.evidence) <= 12
    assert len(context.prompt) < 25000

    manifest = json.loads((ROOT / "data" / "demo" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("release") == "1.0.0"
    assert len(manifest.get("assets", [])) == 3

    for required in [
        ROOT / "LICENSE",
        ROOT / "README.md",
        ROOT / "Projeto_Final_Artefatos" / "README.md",
        ROOT / "docs" / "ARCHITECTURE.md",
        ROOT / "docs" / "README.md",
        ROOT / "docs" / "GOVERNANCE.md",
        ROOT / "docs" / "DATA_SOURCES.md",
        ROOT / "data" / "synthetic" / "multimodal" / "vitaguard_do_imagem_alpha.png",
        ROOT / "data" / "synthetic" / "multimodal" / "vitaguard_do_scan_alpha.pdf",
    ]:
        assert required.exists(), required

    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Projeto Final" in source
    assert "Nova conversa" in source

    print("[OK] Demo 3-way e Comparison Engine disponíveis.")
    print("[OK] 6 fast paths do Ask VitaGuard funcionam sem Gemini.")
    print(f"[OK] Contexto livre compacto: chars={len(context.prompt)} | rows={context.rows_count} | evidence={len(context.evidence)}")
    print("[OK] Assets multimodais, documentação e pasta de artefatos presentes.")
    print("[OK] Release v1.0.0 pronta para smoke test local e publicação no GitHub.")


if __name__ == "__main__":
    main()

# VitaGuard D&O

**Projeto Final InsurMinds — I2A2**  
Plataforma inteligente para análise e comparação de apólices **D&O (Directors & Officers)**.

O VitaGuard recebe documentos em PDF ou imagem, extrai e estrutura informações relevantes com IA Generativa, preserva evidências por página e trecho, compara **2..N apólices** com regras determinísticas e oferece o **Ask VitaGuard**, uma camada conversacional para explicar resultados em linguagem natural.

> **Princípio central:** o LLM interpreta e explica; a comparação de igualdade, diferença, presença e revisão permanece em Python determinístico.

## Principais recursos

- leitura de PDF com texto nativo via PyMuPDF;
- fallback Gemini multimodal para PDFs escaneados, páginas sem texto e PNG/JPG/JPEG/WEBP;
- extração estruturada em `PolicyRecord` com estados explícitos de ausência e ambiguidade;
- evidências rastreáveis por documento, página, seção, trecho e chunk;
- Comparison Engine determinístico para **2..N apólices**;
- franquias e sublimites comparados respeitando o escopo da cobertura;
- famílias harmonizadas para aproximar conceitos editorialmente diferentes sem declarar equivalência contratual;
- interface Streamlit com **Demonstração** e **Analisar documentos**;
- Ask VitaGuard com perguntas rápidas locais, perguntas livres com Gemini, evidências e guardrails;
- cache e retomada para processamento vivo;
- modo Demo autossuficiente com Allianz, AIG e uma apólice VitaGuard Executive Plus **sintética**.

## Execução rápida no Windows

Pré-requisito: **Python 3.11+**.

1. Baixe ou clone o repositório.
2. Execute `run_vitaguard.bat`.
3. Na primeira execução, o launcher cria `.venv`, instala as dependências e executa a validação da release.
4. A aplicação abre em `http://localhost:8501`.

No modo **Demonstração**, a comparação e as perguntas cobertas pelos fast paths locais funcionam sem API key.

Para **Analisar documentos** ou realizar perguntas livres no Ask VitaGuard, informe uma Gemini API key na interface ou defina `GEMINI_API_KEY` no ambiente.

## Execução manual

### Windows

```cmd
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python scripts\validate_v100.py
python -m streamlit run streamlit_app.py
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/validate_v100.py
python -m streamlit run streamlit_app.py
```

## Como usar

### Demonstração

O modo Demo carrega três registros já estruturados:

- Allianz Seguros S.A.;
- AIG Seguros Brasil S.A.;
- VitaGuard Executive Plus — **demonstração sintética**.

Esse modo permite navegar pela comparação, evidências, revisões e parte do Ask VitaGuard sem depender do processamento de novos documentos.

### Analisar documentos

1. Selecione **Analisar documentos**.
2. Informe a Gemini API key quando necessário.
3. Envie pelo menos dois documentos em PDF ou imagem.
4. Aguarde a ingestão, extração e estruturação.
5. Navegue pela comparação, evidências e revisões.

PDFs com texto usam extração nativa quando possível. Páginas sem texto suficiente e imagens usam fallback multimodal.

### Ask VitaGuard

O assistente explica resultados já estruturados e recupera evidências relevantes. Perguntas frequentes podem ser respondidas localmente; perguntas livres usam Gemini com contexto compacto.

O assistente **não decide a comparação**, **não recomenda contratação** e **não substitui análise jurídica ou profissional de seguros**.

## Arquitetura resumida

```text
PDF / imagem
   ↓
Ingestão
   ├─ texto nativo (PyMuPDF)
   └─ fallback multimodal (Gemini)
   ↓
Extração semântica (Gemini)
   ↓
PolicyRecord + evidências
   ↓
Validação / normalização
   ↓
Comparison Engine 2..N (Python)
   ↓
Application Service
   ↓
Streamlit
   ├─ visão geral
   ├─ comparação
   ├─ evidências
   ├─ revisões
   └─ Ask VitaGuard
```

A descrição detalhada está em [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Tecnologias

- Python 3.11+
- Pydantic
- PyYAML
- PyMuPDF
- Google Gemini via `google-genai`
- Streamlit
- Pytest

## Estrutura do repositório

```text
vitaguard_do/
├── application/      # Application Service, processamento vivo e Ask VitaGuard
├── comparison/       # comparação determinística e harmonização
├── extraction/       # seleção, prompts, provider, montagem e evidências
├── ingestion/        # PDF, texto e multimodal
├── models/           # schema de domínio
├── taxonomy/         # taxonomia canônica em YAML
└── validation/       # validações auxiliares

data/
├── demo/             # registros estruturados usados no modo Demonstração
├── real/             # metadados e fingerprints das fontes públicas
└── synthetic/        # documentos sintéticos usados nos testes

docs/                 # documentação pública do projeto
scripts/              # utilitários e validator da release
tests/                # suíte de regressão
Projeto_Final_Artefatos/  # relatório, pitch, vídeo e materiais da entrega acadêmica
```

## Testes

Para executar a suíte completa:

```cmd
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts\validate_v100.py
```

A release foi validada com **144 testes automatizados**, além de smoke tests manuais de PDF textual, imagem, PDF escaneado, comparação 2..N e Ask VitaGuard.

Mais detalhes em [`docs/TESTING.md`](docs/TESTING.md).

## Dados reais e reprodutibilidade

Os PDFs reais de Allianz e AIG não são redistribuídos no repositório. As fontes oficiais e fingerprints usados no desenvolvimento estão documentados em [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) e `data/real/sources.json`.

Os dados estruturados do modo Demonstração servem para tornar a apresentação reproduzível. A VitaGuard Executive Plus é **sintética** e é identificada como tal na interface.

## Segurança, governança e limites

- API keys digitadas na interface são usadas em memória e não são persistidas pelo VitaGuard;
- o Comparison Engine não delega igualdade/diferença ao LLM;
- `Não identificado` não significa inexistência jurídica;
- famílias harmonizadas não significam equivalência contratual;
- referências do Ask VitaGuard são verificadas contra as evidências recuperadas;
- ambiguidades podem permanecer como `REVISAR` para supervisão humana;
- o sistema é um **MVP acadêmico**, não uma ferramenta de aconselhamento jurídico ou recomendação de compra.

Consulte também [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) e [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Documentação

- [`docs/README.md`](docs/README.md) — índice da documentação;
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — arquitetura e componentes;
- [`docs/TECHNICAL_DECISIONS.md`](docs/TECHNICAL_DECISIONS.md) — decisões e justificativas;
- [`docs/TESTING.md`](docs/TESTING.md) — testes e benchmarks;
- [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) — guardrails, transparência e supervisão humana;
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) — limitações conhecidas;
- [`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md) — roteiro de demonstração;
- [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) — fontes públicas utilizadas.

## Equipe

- Lucas Lima Simões
- Raphael Hilário Alcova Coelho
- Patricia Tavares Simões
- Willian Mello Antunes

## Repositório

https://github.com/LucasLimaSimoes/VitaGuard-D-O

## Licença

Distribuído sob a licença **MIT**. Consulte [`LICENSE`](LICENSE).

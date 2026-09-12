# Arquitetura

## Visão geral

O VitaGuard separa **interpretação semântica** de **decisão comparativa**.

LLMs são utilizados onde linguagem e estrutura documental exigem interpretação. Python determinístico é responsável por validar, normalizar, alinhar e comparar os resultados.

```text
Entrada (PDF / imagem)
        ↓
Ingestion Layer
  ├─ PyMuPDF: texto nativo
  └─ Gemini multimodal: scan/imagem/página sem texto suficiente
        ↓
Structured Extraction
  ├─ seleção de chunks
  ├─ Gemini
  ├─ validação Pydantic
  ├─ normalização
  └─ validação de evidências
        ↓
PolicyRecord
        ↓
Comparison Engine 2..N
  ├─ canonical_id
  ├─ escopo financeiro (applies_to)
  ├─ status determinísticos
  └─ famílias harmonizadas
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

## Camadas

### Ingestão — `vitaguard_do/ingestion/`

Recebe PDF ou imagem e transforma o conteúdo em páginas textuais rastreáveis.

- PDF com texto: PyMuPDF;
- PDF misto: texto nativo onde disponível e fallback somente nas páginas necessárias;
- PDF escaneado e imagens: Gemini multimodal.

A origem do texto é preservada para distinguir leitura nativa de recuperação multimodal.

### Extração — `vitaguard_do/extraction/`

Converte conteúdo textual em fatos estruturados.

A saída do modelo passa por validação local Pydantic, normalização e validação de evidências. Valores ausentes ou ambíguos não são preenchidos silenciosamente.

### Modelo de domínio — `vitaguard_do/models/`

O principal contrato estruturado é o `PolicyRecord`. Os campos extraídos carregam status, valor, confiança, evidências e observações quando aplicável.

### Taxonomia — `vitaguard_do/taxonomy/`

A taxonomia canônica fica em YAML, separada do schema de domínio. Isso permite ajustar mapeamentos sem alterar o contrato estrutural dos objetos.

### Comparação — `vitaguard_do/comparison/`

O motor recebe uma lista de `PolicyRecord`s e produz uma única matriz 2..N.

Status principais:

- `EQUAL`;
- `DIFFERENT`;
- `ONLY_IN_SOME`;
- `ALL_MISSING`;
- `NEEDS_REVIEW`.

O LLM não decide igualdade ou diferença.

### Harmonização

Alguns produtos organizam proteções equivalentes ou relacionadas em seções editoriais diferentes. O VitaGuard mantém os dados estruturais originais e adiciona famílias comparativas para navegação.

Essas famílias **não declaram equivalência jurídica ou contratual**.

### Application Service — `vitaguard_do/application/`

A camada de aplicação isola a interface dos detalhes internos do domínio.

- `service.py`: operações de alto nível;
- `live.py`: jobs, processamento vivo, cache e retomada;
- `assistant.py`: contexto, fast paths e guardrails do Ask VitaGuard.

### Interface — `streamlit_app.py`

A interface oferece dois modos:

- **Demonstração**: dados já estruturados e reproduzíveis;
- **Analisar documentos**: pipeline vivo de ingestão, extração e comparação.

As áreas principais são Visão geral, Comparação, Evidências, Revisões e Ask VitaGuard.

## Ask VitaGuard

Perguntas frequentes usam caminhos locais determinísticos. Perguntas livres recebem contexto compacto formado por linhas comparativas, glossário, famílias e evidências recuperadas.

As referências citadas pelo modelo são validadas localmente antes da exibição. IDs internos são humanizados e pedidos de recomendação de contratação são bloqueados ou redirecionados para critérios neutros de comparação.

## Persistência do MVP

O projeto não exige banco de dados. Jobs vivos usam `outputs/live/<job_id>/` para cache e retomada. O histórico do chat existe somente na sessão Streamlit.

## Credenciais

A Gemini API key pode ser fornecida por variável de ambiente ou por campo protegido da interface. A aplicação não grava a chave nos jobs, manifests ou assets de demonstração.

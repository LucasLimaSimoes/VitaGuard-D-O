# Decisões técnicas

## LLM para semântica; Python para decisão

Cláusulas e conceitos jurídicos exigem interpretação de linguagem natural. Já igualdade, presença, normalização numérica e regras de comparação precisam ser reproduzíveis. Por isso o LLM não atua como árbitro do Comparison Engine.

## Evidência como parte do dado

Cada fato relevante deve carregar origem suficiente para auditoria. A interface permite voltar da conclusão ao documento, página e trecho correspondente.

## Estados explícitos para ausência e ambiguidade

`FOUND`, `NOT_FOUND`, `AMBIGUOUS`, `NOT_APPLICABLE` e `CONFLICTING` preservam diferenças que seriam perdidas caso tudo fosse reduzido a `null`.

Na interface, `Não identificado` nunca é apresentado como prova de inexistência jurídica.

## Comparação nativa 2..N

O motor recebe uma lista de apólices, não um par A/B fixo. O mesmo código gera matrizes com duas, três ou mais apólices.

## Valores financeiros com escopo

Franquias e sublimites podem coexistir para Side A, Side B, Side C ou outras coberturas. O alinhamento considera conceito + `applies_to`, evitando falsos conflitos.

## Harmonização não destrutiva

Famílias comparativas ajudam a reconhecer proteções relacionadas que aparecem em categorias editoriais diferentes. O dado original permanece intacto e continua auditável.

## Multimodal apenas quando necessário

PDF com texto nativo usa PyMuPDF. Imagens e páginas sem texto suficiente usam Gemini multimodal. Isso reduz custo e evita substituir texto nativo de boa qualidade por uma nova interpretação.

## Cache e retomada

Um `job_id` determinístico permite reaproveitar transcrição multimodal e estágios estruturados quando o mesmo conjunto de documentos é processado novamente.

## Ask VitaGuard fundamentado

O assistente não recebe indiscriminadamente todos os documentos. O contexto é montado a partir do `ComparisonReport`, glossário, famílias e evidências relevantes.

Perguntas frequentes são respondidas localmente; perguntas livres usam contexto compacto e referências verificáveis.

## Streamlit para o MVP

O objetivo acadêmico exigia uma aplicação funcional e demonstrável em prazo curto. Streamlit reduziu o custo de integração e permitiu concentrar esforço em extração, rastreabilidade, comparação e governança.

Uma evolução de produto poderia separar frontend e API sem alterar o núcleo de domínio.

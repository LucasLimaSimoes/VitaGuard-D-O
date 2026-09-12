from __future__ import annotations

from collections import defaultdict

from vitaguard_do.taxonomy.loader import TaxonomyRegistry


SYSTEM_RULES = """
- Seja compacto e nao copie o prompt/taxonomia para os campos.

Voce e um extrator de dados de documentos de seguro D&O.
Regras obrigatorias:
1. Use SOMENTE o texto dos chunks fornecidos. Nao use conhecimento externo para preencher lacunas.
2. Nao invente informacoes. Se um campo escalar nao estiver no texto, marque NOT_FOUND.
3. Toda informacao marcada FOUND deve ter pelo menos uma evidencia.
4. A evidencia deve citar um chunk_id fornecido, a pagina correta e um excerpt VERBATIM existente nesse chunk.
5. Nao parafraseie o excerpt de evidencia.
6. Para canonical_id/canonical_term, use apenas IDs permitidos na taxonomia fornecida. Se nao houver correspondencia segura, use null.
7. Diferencie limite geral da apolice de sublimites de coberturas/extensoes.
8. Diferencie franquias/retencoes por cobertura usando applies_to quando houver correspondencia canonica.
9. Confidence representa confianca de extracao/normalizacao, nao probabilidade estatistica.
10. O documento pode ser sintetico; trate o conteudo como documento de teste e extraia normalmente.
""".strip()


CORE_FIELDS = [
    "insurer",
    "product_name",
    "susep_process",
    "policy_number",
    "insured",
    "policyholder",
    "document_version",
    "policy_period_start",
    "policy_period_end",
    "currency",
    "retroactive_date",
    "extended_reporting_period",
    "geographic_scope",
    "jurisdiction",
    "coverage_trigger",
]

FINANCIAL_FIELDS = [
    "premium",
    "maximum_guarantee_limit",
    "aggregate_limit",
    "deductible",
]


def taxonomy_context(registry: TaxonomyRegistry, categories: tuple[str, ...]) -> str:
    grouped = defaultdict(list)
    for item in registry.items:
        if item.category in categories:
            grouped[item.category].append(item)

    lines: list[str] = []
    for category in categories:
        lines.append(f"[{category}]")
        for item in sorted(grouped.get(category, []), key=lambda x: x.id):
            aliases = ", ".join(item.aliases)
            lines.append(f"- {item.id}: {item.label} | aliases: {aliases}")
    return "\n".join(lines)


def core_prompt(chunks_text: str, registry: TaxonomyRegistry, *, long_document: bool = False) -> str:
    financial_tax = taxonomy_context(registry, ("financial_fields", "coverages"))
    long_rules = """
MODO DOCUMENTO REAL LONGO:
- Este pode ser um caderno de Condicoes Gerais, e nao uma apolice emitida individualmente.
- Nao invente numero de apolice, segurado, premio, LMG, franquia ou datas de vigencia quando o texto apenas disser que esses valores constam da Especificacao da Apolice.
- Priorize os fatos efetivamente presentes nos chunks selecionados.
""".strip() if long_document else ""
    return f"""
{SYSTEM_RULES}

TAREFA: extraia identificacao, termos contratuais e valores financeiros.
{long_rules}

SCALAR field_id obrigatorios (retorne exatamente uma entrada para cada ID):
{', '.join(CORE_FIELDS)}

FINANCIAL field_id permitidos:
{', '.join(FINANCIAL_FIELDS)}

Regras de normalizacao:
- Datas em normalized_value devem usar YYYY-MM-DD quando houver uma data unica.
- Para policy_period_start e policy_period_end, use as datas inicial e final separadamente.
- currency deve preferencialmente ser codigo ISO (ex.: BRL) quando explicito.
- Para MONEY, numeric_value deve ser o valor numerico sem separadores de milhar; currency deve ser informada quando conhecida.
- Para DURATION, numeric_value e unit devem representar a duracao (ex.: 12 + months).
- Para franquias/retencoes, use field_id=deductible e applies_to com IDs canonicos de cobertura quando possivel.
- 'Sem franquia'/'Sem retencao' deve ser MONEY com numeric_value=0 quando a moeda da apolice for conhecida.
- Nao extraia sublimites de cobertura como limite geral; sublimites serao extraidos em outra etapa.

TAXONOMIA RELEVANTE:
{financial_tax}

CHUNKS DISPONIVEIS:
{chunks_text}
""".strip()


def risk_prompt(chunks_text: str, registry: TaxonomyRegistry, *, long_document: bool = False) -> str:
    tax = taxonomy_context(registry, ("coverages", "extensions", "exclusions", "financial_fields"))
    long_rules = """
MODO DOCUMENTO REAL LONGO:
- Priorize itens que possam ser mapeados com seguranca para a taxonomia.
- Inclua no maximo 8 itens significativos sem canonical_id para revelar lacunas da taxonomia.
- Nao extraia itens apenas porque aparecem no sumario; use o texto contratual dos chunks.
- Uma mesma ideia pode aparecer como cobertura ou extensao conforme a seguradora; preserve a classificacao usada no documento.
""".strip() if long_document else ""
    return f"""
{SYSTEM_RULES}

TAREFA: extraia coberturas, extensoes e exclusoes presentes nos chunks.
{long_rules}

Regras adicionais:
- Retorne apenas itens efetivamente presentes.
- original_name deve preservar o titulo/nome usado no documento.
- description deve resumir fielmente o texto, sem adicionar interpretacao externa.
- Excecoes expressas a uma exclusao devem ser registradas em exceptions.
- Condicoes relevantes de cobertura/extensao devem ser registradas em conditions.
- Sublimites ligados a uma cobertura/extensao devem aparecer em financials com field_id=coverage_sublimit.
- Nao transforme Limite Maximo de Garantia ou limite agregado em sublimite.
- canonical_id deve usar a taxonomia quando houver correspondencia segura; caso contrario, null.

TAXONOMIA:
{tax}

CHUNKS DISPONIVEIS:
{chunks_text}
""".strip()


def semantic_prompt(chunks_text: str, registry: TaxonomyRegistry, *, long_document: bool = False) -> str:
    tax = taxonomy_context(registry, ("definitions", "clauses"))
    long_rules = """
MODO DOCUMENTO REAL LONGO:
- Priorize definicoes e clausulas que tenham correspondencia segura na taxonomia.
- Inclua no maximo 5 itens relevantes sem canonical_id/canonical_term para revelar lacunas.
- Para definicoes, prefira o verbete formal (TERMO: definicao) em vez de mencoes incidentais.
- Para clausulas, prefira o titulo formal da clausula quando presente.
""".strip() if long_document else ""
    return f"""
{SYSTEM_RULES}

TAREFA: extraia definicoes contratuais e clausulas/condicoes relevantes.
{long_rules}

Regras adicionais:
- Definicoes: original_term = termo como aparece; definition_text = definicao fiel ao documento.
- Clausulas: original_name = titulo/nome; summary = resumo fiel do efeito contratual observado no texto.
- canonical_term/canonical_id deve usar a taxonomia quando houver correspondencia segura; caso contrario, null.
- Nao crie uma definicao ou clausula apenas porque existe na taxonomia: ela precisa estar no texto.

TAXONOMIA:
{tax}

CHUNKS DISPONIVEIS:
{chunks_text}
""".strip()



def definitions_prompt(
    chunks_text: str,
    registry: TaxonomyRegistry,
    *,
    long_document: bool = False,
    required_candidates: list[str] | None = None,
) -> str:
    tax = taxonomy_context(registry, ("definitions",))
    candidates = required_candidates or []
    checklist = "\n".join(f"- {item}" for item in candidates) or "- nenhum candidato formal detectado"
    long_rules = """
MODO DOCUMENTO REAL LONGO:
- Extraia SOMENTE definicoes contratuais formais; nao inclua clausulas nesta resposta.
- Prefira verbetes numerados/rotulados do glossario a mencoes incidentais.
- Seja compacto: uma evidencia curta e literal por definicao normalmente basta.
- Nao copie listas longas quando uma definicao puder ser representada fielmente de forma mais curta.
""".strip() if long_document else ""
    return f"""
{SYSTEM_RULES}

TAREFA: extraia apenas definicoes contratuais presentes nos chunks.
{long_rules}

CHECKLIST DETERMINISTICO DE CANDIDATOS FORMAIS VISIVEIS NOS CHUNKS:
{checklist}

Regras de completude:
- Para CADA canonical_term listado no checklist, verifique explicitamente o verbete formal nos chunks.
- Se o texto definidor estiver visivel, o verbete NAO pode ser omitido da lista definitions.
- Se o heading estiver cortado e nao houver texto suficiente para uma definicao fiel, nao invente: registre um warning curto.
- original_term deve preservar o termo do documento; definition_text deve ser fiel e compacto.
- canonical_term deve usar a taxonomia quando houver correspondencia segura; caso contrario, null.
- Nao crie definicoes apenas porque existem na taxonomia.

TAXONOMIA DE DEFINICOES:
{tax}

CHUNKS DISPONIVEIS:
{chunks_text}
""".strip()


def clauses_prompt(
    chunks_text: str,
    registry: TaxonomyRegistry,
    *,
    long_document: bool = False,
    required_candidates: list[str] | None = None,
) -> str:
    tax = taxonomy_context(registry, ("clauses",))
    candidates = required_candidates or []
    checklist = "\n".join(f"- {item}" for item in candidates) or "- nenhum candidato formal detectado"
    long_rules = """
MODO DOCUMENTO REAL LONGO:
- Extraia SOMENTE clausulas/condicoes contratuais relevantes; nao inclua definicoes nesta resposta.
- Prefira o titulo formal da clausula quando presente.
- Seja compacto: uma evidencia curta e literal por clausula normalmente basta.
""".strip() if long_document else ""
    return f"""
{SYSTEM_RULES}

TAREFA: extraia apenas clausulas/condicoes contratuais relevantes presentes nos chunks.
{long_rules}

CHECKLIST DETERMINISTICO DE CANDIDATOS FORTES VISIVEIS NOS CHUNKS:
{checklist}

Regras de completude:
- Para cada canonical_id listado no checklist, confirme o texto nos chunks e nao o omita quando a clausula formal estiver visivel.
- Se nao houver texto suficiente, nao invente; use warnings.
- original_name deve preservar o titulo/nome do documento; summary deve resumir fielmente o efeito observado.
- canonical_id deve usar a taxonomia quando houver correspondencia segura; caso contrario, null.

TAXONOMIA DE CLAUSULAS:
{tax}

CHUNKS DISPONIVEIS:
{chunks_text}
""".strip()


def coverages_extensions_prompt(
    chunks_text: str,
    registry: TaxonomyRegistry,
    *,
    long_document: bool = False,
    required_candidates: list[str] | None = None,
) -> str:
    tax = taxonomy_context(registry, ("coverages", "extensions", "financial_fields"))
    candidates = required_candidates or []
    checklist = "\n".join(f"- {item}" for item in candidates) or "- nenhum candidato forte detectado"
    long_rules = """
MODO DOCUMENTO REAL LONGO:
- Extraia SOMENTE coberturas e extensoes nesta resposta; nao inclua exclusoes.
- Preserve a classificacao do documento (cobertura vs extensao).
- Seja compacto: uma evidencia curta e literal por item normalmente basta.
- Sublimites pertencentes a um item devem ficar em financials; nao confunda com LMG global.
""".strip() if long_document else ""
    return f"""
{SYSTEM_RULES}

TAREFA: extraia apenas coberturas e extensoes presentes nos chunks.
{long_rules}

CHECKLIST DETERMINISTICO DE CANDIDATOS FORTES VISIVEIS NOS CHUNKS:
{checklist}

Regras de completude:
- Para CADA entrada `categoria:canonical_id` do checklist, confirme o texto contratual nos chunks.
- Se duas entradas de categorias diferentes claramente apontarem para o MESMO heading, nao duplique o item: preserve apenas a classificacao usada pelo documento.
- Se o item estiver formalmente presente, ele NAO pode ser omitido da resposta sob a categoria correta.
- Se houver apenas mencao cruzada sem texto contratual suficiente, nao invente; registre um warning curto.
- original_name deve preservar o titulo/nome usado no documento.
- canonical_id deve usar a taxonomia quando houver correspondencia segura; caso contrario, null.
- Condicoes relevantes devem ficar em conditions.
- Sublimites devem usar financials com field_id=coverage_sublimit.

TAXONOMIA:
{tax}

CHUNKS DISPONIVEIS:
{chunks_text}
""".strip()


def exclusions_prompt(
    chunks_text: str,
    registry: TaxonomyRegistry,
    *,
    long_document: bool = False,
    required_candidates: list[str] | None = None,
) -> str:
    tax = taxonomy_context(registry, ("exclusions",))
    candidates = required_candidates or []
    checklist = "\n".join(f"- {item}" for item in candidates) or "- nenhum candidato forte detectado"
    long_rules = """
MODO DOCUMENTO REAL LONGO:
- Extraia SOMENTE exclusoes nesta resposta; nao inclua coberturas, extensoes ou definicoes.
- Prefira o heading formal numerado/rotulado da exclusao a mencoes incidentais.
- Seja compacto: uma evidencia curta e literal por exclusao normalmente basta.
""".strip() if long_document else ""
    return f"""
{SYSTEM_RULES}

TAREFA: extraia apenas exclusoes presentes nos chunks.
{long_rules}

CHECKLIST DETERMINISTICO DE EXCLUSOES FORTES VISIVEIS NOS CHUNKS:
{checklist}

Regras de completude:
- Para CADA `exclusions:canonical_id` listado, verifique explicitamente o heading/texto nos chunks.
- Se a exclusao formal estiver visivel, ela NAO pode ser omitida da lista exclusions.
- Se o heading estiver cortado e nao houver texto suficiente para uma descricao fiel, nao invente; registre um warning.
- original_name deve preservar o titulo/nome do documento.
- description deve resumir apenas o que o texto afirma.
- Excecoes expressas devem ficar em exceptions.
- canonical_id deve usar a taxonomia quando houver correspondencia segura; caso contrario, null.

TAXONOMIA DE EXCLUSOES:
{tax}

CHUNKS DISPONIVEIS:
{chunks_text}
""".strip()

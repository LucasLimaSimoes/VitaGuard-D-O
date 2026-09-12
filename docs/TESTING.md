# Testes e validação

## Execução

```cmd
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts\validate_v100.py
```

## Suíte automatizada

A release v1.0.0 foi fechada com **144 testes automatizados**.

A suíte cobre:

- schema e taxonomia;
- ingestão e chunking;
- provider Gemini, retries e recuperação de saída;
- extração estruturada e cache por estágio;
- validação de evidências;
- benchmarks sintéticos;
- regressões de fontes reais Allianz/AIG;
- Comparison Engine 2..N;
- normalização contratual;
- harmonização comparativa;
- Application Service;
- ingestão multimodal;
- estados e hotfixes do frontend;
- Ask VitaGuard, guardrails, composer e fast paths.

## Benchmarks de desenvolvimento

Os dois documentos sintéticos atingiram 100% nos indicadores definidos durante a estabilização do pipeline.

No benchmark real AIG, a versão estabilizada atingiu 100% em fatos, páginas de evidência e validade determinística dentro do conjunto ouro usado no projeto.

No benchmark Allianz, fatos e páginas esperadas foram fechados em 100%, com evidência determinística estabilizada para o escopo utilizado.

Esses benchmarks detectam regressões do pipeline e **não representam certificação jurídica das apólices**.

## Smoke tests manuais realizados

- Demo 3-way: Allianz + AIG + VitaGuard Executive Plus sintética;
- PDF textual vivo;
- PNG/JPG via Gemini multimodal;
- PDF image-only via Gemini multimodal;
- troca de uploads/jobs sem traceback;
- Ask VitaGuard com fast paths e pergunta livre;
- recusa de recomendação de contratação;
- auto-scroll e composer no fim da conversa;
- instalação da release em pasta limpa no Windows.

## Validator da release

`scripts/validate_v100.py` verifica rapidamente:

- carregamento do modo Demo;
- comparação disponível;
- fast paths locais sem Gemini;
- tamanho máximo do contexto livre de referência;
- manifesto da Demo;
- assets e documentos essenciais da release.

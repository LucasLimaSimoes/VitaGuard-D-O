# Changelog

## v1.0.0

- Release final do MVP acadêmico VitaGuard D&O.
- Documentação pública reorganizada para GitHub, com índice técnico, governança e fontes de dados.
- README final inclui equipe, execução, arquitetura resumida, testes e uso responsável.
- Escopo funcional congelado após validação de PDF textual, imagem, PDF escaneado, comparação 2..N e Ask VitaGuard.
- Repositório inclui licença MIT, validator final, requirements de runtime/dev e workflow de CI.
- Criada `Projeto_Final_Artefatos/` para receber relatório, pitch, vídeo e materiais da entrega.
- Nenhuma nova lógica de negócio adicionada em relação à v0.9.1.3.

## v0.9.1.3

- Passagem final de desempenho do **Ask VitaGuard** antes da v1.0.
- As cinco perguntas sugeridas e pedidos diretos de recomendação passam por **fast paths locais determinísticos**, sem chamada Gemini.
- Perguntas frequentes sobre resumo, glossário, presença parcial, proteções em todas e revisão humana respondem a partir do `ComparisonReport`, taxonomia e evidências já calculados.
- Perguntas livres continuam usando Gemini, mas o contexto foi reduzido de 10 para até 7 linhas e de 20 para até 12 evidências, com payloads JSON compactos.
- Campos internos desnecessários foram removidos do prompt do assistente, reduzindo aproximadamente pela metade o tamanho do contexto no benchmark Demo.
- O provider interativo usa limite de saída menor, uma tentativa por modo/modelo e sem intervalo artificial entre chamadas.
- Cache de resposta em memória por sessão + conjunto de apólices evita repetir a mesma chamada exata.
- Perguntas locais podem ser usadas sem API key; perguntas realmente generativas continuam pedindo Gemini.
- Nenhuma alteração no Comparison Engine, extração, multimodal ou evidências.

## v0.9.1.2

- Hotfix final de transparência e governança do frontend.
- Referências internas do harness, como `[Regra 9]` e `[Regras 1, 13]`, são removidas deterministicamente da resposta antes da exibição.
- Pedidos diretos de recomendação continuam sem indicar contratação, mas agora oferecem critérios neutros úteis para apoiar a decisão.
- O prompt proíbe explicitamente a exposição de números de regras, instruções internas e detalhes do harness.
- A **VitaGuard Executive Plus** passa a ser marcada como **Sintética** na sidebar/seleção e como **Demonstração sintética** nos detalhes.
- Evidências do Ask VitaGuard também sinalizam quando pertencem à demonstração sintética.
- O botão `Limpar chat` foi renomeado para **Nova conversa**.
- Fluxos PDF/imagem, comparação determinística, auto-scroll e composer no fim da conversa foram preservados.

## v0.9.1.1

- Último refinamento visual/conversacional antes do fechamento do MVP.
- Chat acompanha automaticamente a conversa usando âncora + `scrollIntoView`, sem alterar a lógica do assistente.
- Respostas do Ask VitaGuard ganham layout mais escaneável e prompt orientado a **Em resumo** + detalhes curtos.
- Novo pós-processamento converte canonical/comparison IDs em rótulos humanos e preserva referências `[E#]`.
- Evidências passam a mostrar até três referências principais antes do conjunto completo.
- Metadados de modelo/contexto foram movidos para **Como esta resposta foi construída**.
- Perguntas sugeridas ficam compactas após a primeira interação.
- Feedback 👍/👎 por resposta foi adicionado à sessão, apoiando avaliação humana/contínua.
- UI recebe hero e cards refinados, métricas estilizadas, badges de controles e melhor acabamento visual.
- Ask VitaGuard explicita contexto fundamentado, guardrails, rastreabilidade e revisão humana.
- Novo `validate_v091.py` e testes de regressão para UX/guardrails.
- Fluxos PDF textual, multimodal, comparação 2..N e modo Demonstração preservados.

## v0.9.0

- Nova aba **Ask VitaGuard** no modo Demonstração e no modo vivo.
- Perguntas livres em linguagem natural e cinco perguntas sugeridas.
- Recuperação local/determinística de linhas relevantes, famílias harmonizadas, glossário e evidências.
- Respostas Gemini estruturadas, com referências `[E#]` e validação local dos IDs citados.
- Evidências usadas aparecem com apólice, conceito, página e trecho.
- Guardrails explícitos para `Não identificado`, famílias harmonizadas, aconselhamento jurídico e recomendação de contratação.
- Histórico do chat isolado por conjunto de apólices e mantido somente na sessão Streamlit.
- Chave Gemini pode ser reaproveitada da análise viva, lida do ambiente ou digitada somente na aba do assistente.
- Fluxo PDF/imagem e Comparison Engine da v0.8.1.1 preservados.

## v0.8.1.1

- Hotfix de UX/estado do modo **Analisar documentos**.
- Ao trocar os arquivos carregados, o VitaGuard não tenta mais recomparar o bundle anterior.
- A seleção de apólices vivas é reinicializada quando o `job_id` muda.
- Erros recuperáveis de seleção/comparação são exibidos como mensagens amigáveis, sem traceback bruto na interface.
- Rótulos curtos duplicados são desambiguados pelo arquivo de origem, por exemplo `VitaGuard · Imagem Alpha` e `VitaGuard · Imagem Beta`.
- Fluxo multimodal da v0.8.1 preservado sem alterações funcionais.

## v0.8.1

- Suporte vivo a PDF, PNG, JPG/JPEG e WEBP.
- Fallback Gemini multimodal para páginas de PDF com pouco ou nenhum texto nativo.
- PDFs mistos usam leitura multimodal somente nas páginas necessárias.
- Imagens são tratadas como documentos de uma página com evidência `page_number=1`.
- Cache dedicado de transcrição em `outputs/live/<job_id>/multimodal_cache/`.
- `IngestedPage.text_origin` distingue texto nativo de texto recuperado por Gemini multimodal.
- `IngestionStats.multimodal_text_pages` e `LiveDocumentArtifact.multimodal_text_pages` expõem a origem do texto na UI.
- Interface passa a aceitar PDF/imagem e mostra contagem nativa/multimodal por documento.
- Incluídos dois PNGs sintéticos e dois PDFs image-only para smoke test multimodal.
- Novo validator `validate_v081.py`.
- Nenhuma dependência física de versões anteriores.


## v0.8.0

- Primeiro fluxo vivo end-to-end no Streamlit.
- Upload de 2+ PDFs e processamento via Gemini.
- API key digitada na UI (memória) ou `GEMINI_API_KEY` no ambiente.
- Jobs determinísticos em `outputs/live/<job_id>/`.
- Cache por estágio para retomada após falhas/quota.
- Application Service passa a suportar `LiveAnalysisBundle`.
- Comparison Engine reutilizado sem LLM para decisão de igualdade/diferença.
- Modo Demonstração preservado e autossuficiente.
- Launcher local passa a instalar/validar dependências completas (`PyMuPDF`, `google-genai`, Streamlit etc.).
- Limitação explícita: fluxo vivo v0.8.0 requer PDF com texto nativo.

## v0.7.3

- Frontend demonstrativo estabilizado.
- Melhorias finais de UX, formatação e leitura da matriz.

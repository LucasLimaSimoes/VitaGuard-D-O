# Governança, segurança e uso responsável

## Separação de responsabilidades

O VitaGuard não usa o LLM como fonte final de verdade para a comparação. A IA interpreta documentos e explica resultados; validação estrutural e comparação permanecem em código determinístico.

## Rastreabilidade

Fatos extraídos podem carregar:

- documento de origem;
- página;
- seção;
- trecho;
- chunk.

O Ask VitaGuard referencia somente evidências presentes no contexto recuperado e validado pela aplicação.

## Ausência não significa inexistência

`Não identificado` indica que o dado não foi localizado no `PolicyRecord` atual. Isso não comprova que a cobertura, cláusula ou condição não exista juridicamente no contrato completo.

## Harmonização não significa equivalência

Famílias comparativas agrupam conceitos próximos para facilitar navegação entre documentos com estruturas editoriais diferentes. Elas não afirmam identidade jurídica, contratual ou de extensão de cobertura.

## Revisão humana

Casos ambíguos podem permanecer como `NEEDS_REVIEW`. O sistema prefere expor a incerteza a escolher silenciosamente entre ocorrências concorrentes.

## Ask VitaGuard

O assistente:

- explica dados estruturados e comparações;
- pode definir termos e resumir diferenças;
- mostra evidências quando disponíveis;
- não recomenda qual seguro contratar;
- não substitui corretor, subscritor, advogado ou especialista em seguros.

## Credenciais

API keys fornecidas pela interface são utilizadas em memória. Arquivos de configuração local e secrets do Streamlit estão protegidos pelo `.gitignore`.

## Dados de demonstração

A VitaGuard Executive Plus é uma apólice sintética criada para teste e demonstração. A interface a identifica explicitamente como sintética.

Allianz e AIG são usados a partir de fontes públicas documentadas; os PDFs originais não são redistribuídos no repositório.

# Limitações conhecidas

- várias imagens/fotos são tratadas como documentos independentes, não como páginas de uma mesma apólice;
- a qualidade do fallback multimodal depende de resolução, orientação e legibilidade;
- PDFs escaneados extensos podem aumentar latência e consumo de cota do Gemini;
- o MVP usa cache em arquivos, não banco de dados multiusuário;
- não há autenticação, autorização ou infraestrutura de alta disponibilidade;
- o Ask VitaGuard usa recuperação lexical/determinística, não um RAG vetorial completo;
- feedback 👍/👎 é mantido apenas na sessão;
- documentos de Condições Gerais podem não conter limites, prêmio, segurado e dados presentes apenas na Especificação da Apólice;
- `Não identificado` significa ausência no registro estruturado atual, não prova de ausência jurídica;
- famílias harmonizadas representam proximidade para navegação, não equivalência contratual;
- a qualidade da extração depende do documento de entrada e do comportamento do modelo utilizado;
- o sistema é um protótipo acadêmico e não substitui corretor, subscritor, advogado ou especialista em D&O.

# Guardrail Anti-Alucinação do Cathedra

## Objetivo

Atuar como guardrail de qualidade factual para as notas acadêmicas geradas pelo Cathedra (capítulo de aula, Zettels atômicos e tensões dialéticas). O objetivo é impedir erros materiais graves e alucinações reais de modelos de linguagem sem transformar o pipeline em uma auditoria forense citação a citação.

Esta especificação substitui o fluxo legado de `skills/fact-check.md` (voltado a checagem frase por frase de outro cofre) como referência operacional do projeto.

## Política de Referências

1. **Referências exclusivas da aula:** o lastro empírico e bibliográfico da aula vem exclusivamente dos slides extraídos (PDF/PPTX) e da transcrição da fala do professor.
2. **Proibição de citações externas fabricadas:** livros, autores, empresas, casos empíricos ou estatísticas específicas que não apareçam nos slides nem na transcrição devem ser sinalizados como alucinação (`S4`).
3. **Ementa como escopo:** o resumo e os tópicos da ementa situam o contexto curricular da disciplina; a bibliografia listada na ementa não entra como fonte consultada.

## O que o Guardrail NÃO Deve Reportar

Retorne `issues: []` sempre que o texto estiver coerente com a aula e livre de erros materiais ou alucinações. Não registre itens para:
- Paráfrases fiéis do conteúdo dos slides ou da fala do professor.
- Explicações didáticas corretas e intuições conceituais consolidadas da área que ajudam a compreender uma fórmula ou tópico ministrado em aula (por exemplo, explicar por que a variância eleva os desvios ao quadrado ou definir desvio padrão como raiz quadrada da variância).
- Pequenos ruídos fonéticos ou hesitações provenientes da transcrição automática.
- Preferências estilísticas irrelevantes (`S6`).

## O que o Guardrail Deve Barrar ou Corrigir

Registre um `GuardrailIssue` em `issues` somente diante de desvios reais:

| Severidade | Veredito | Critério | Ação esperada |
| --- | --- | --- | --- |
| `S1` | `false` | Fórmula matemática errada, sinal ou regra de decisão invertida, cálculo incorreto em exemplo da aula ou definição tecnicamente falsa. | Informar `proposed_fix` para substituição; bloqueia publicação se não resolvido. |
| `S5` | `misleading` ou `false` | Contradição lógica interna ou conflito direto com uma regra explícita dos slides ou do professor. | Informar `proposed_fix` se houver correção direta; bloqueia publicação se não resolvido. |
| `S4` | `unsupported` | Alucinação evidente: tópico inventado, livro/autor externo não citado na aula, empresa ou dado empírico fabricado. | Definir `proposed_fix: null` para remoção determinística do trecho; bloqueia se não localizado (salvo modo tolerante quando aplicável). |
| `S2` | `imprecise` | Divergência numérica material em exemplo ou tabela da aula. | Informar `proposed_fix` para correção automática. |
| `S3` | `misleading` | Distorção conceitual relevante que altera a conclusão técnica da aula. | Informar `proposed_fix` para ajuste; bloqueia se não resolvido. |

## Contrato de Execução (Passada Única)

- O guardrail executa em **passada única** usando o schema enxuto `GuardrailResponse` (sem veredito `verified` e sem exigência de localizadores literais de citação).
- Todo `GuardrailIssue` deve trazer em `quote` o trecho literal exato e contíguo do rascunho, Zettel ou tensão onde ocorre o problema, permitindo correção ou remoção determinística em Python.
- Qualquer erro crítico (`S1` ou `S5`) não corrigido bloqueia a publicação da aula, inclusive com `--allow-pending-review`, cobrindo corpo principal, Zettels, tensões e citações órfãs.

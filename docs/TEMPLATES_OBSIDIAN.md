# Templates e Marcadores de Idempotencia do Obsidian

O modulo `src/mba_wiki/exporters/obsidian_writer.py` deve seguir estritamente estes formatos ao gerar ou atualizar arquivos no Vault. O exportador inclui suporte a auto-recuperacao de delimitadores estruturais caso sejam acidentalmente danificados durante edicoes manuais.

---

## 1. Indice da Materia (`_Indice_Materia.md`)
Localizacao: `01_Wiki_Disciplinas/<discipline_slug>/_Indice_Materia.md`

Para garantir idempotencia ao adicionar novas aulas, o script substitui apenas o conteudo entre os marcadores `<!-- AUTO-LESSONS:START -->` e `<!-- AUTO-LESSONS:END -->`, preservando qualquer anotacao manual fora deles.

Quando um marcador estiver ausente, `--force` preserva o texto existente e acrescenta um novo bloco. Marcadores duplicados ou invertidos interrompem a escrita; links antigos fora do bloco podem precisar de revisao manual.

```markdown
---
type: moc_disciplina
discipline_slug: "{{ discipline_slug }}"
discipline_name: "{{ discipline_name }}"
professor: "{{ professor }}"
tags:
  - mba/disciplina
  - mba/{{ discipline_slug }}
---

# {{ discipline_name }}

## Ementa e Objetivos
{{ syllabus_summary }}

## Aulas Processadas
<!-- AUTO-LESSONS:START -->
{% for lesson in lessons %}
- [[Aula_{{ "%02d" | format(lesson.lesson_number) }}_{{ lesson.lesson_slug }}|Aula {{ "%02d" | format(lesson.lesson_number) }}: {{ lesson.lesson_title }}]]
{% endfor %}
<!-- AUTO-LESSONS:END -->

## Bibliografia Oficial
{% for item in bibliography %}
- {{ item }}
{% endfor %}
```

---

## 2. Pagina de Aula na Wiki (`Aula_<NN>_<slug_tema>.md`)
Localizacao: `01_Wiki_Disciplinas/<discipline_slug>/Aula_<NN>_<lesson_slug>.md`

O corpo da aula (`body_markdown`), os conceitos atomicos vinculados, conexoes interdisciplinares e tensoes dialeticas ficam protegidos entre marcadores automaticos. Ao reprocessar, todo o texto fora desses marcadores e preservado, inclusive frontmatter, cabecalho e notas pessoais. Por isso, campos do frontmatter representam os valores da criacao da pagina e nao sao atualizados automaticamente; os dados atuais da auditoria constam no JSON correspondente.

Com `--force`, se um ou ambos os marcadores estiverem ausentes, o texto existente e preservado, eventuais marcadores isolados sao removidos e um novo bloco automatico e acrescentado ao final. O conteudo antigo pode permanecer visivel para revisao. Marcadores duplicados ou em ordem invertida impedem a gravacao, inclusive com `--force`.

```markdown
---
type: wiki_aula
discipline_slug: "{{ discipline_slug }}"
discipline_name: "{{ discipline_name }}"
lesson_number: {{ lesson_number }}
lesson_title: "{{ lesson_title }}"
lesson_slug: "{{ lesson_slug }}"
processed_date: {{ processed_date }}
source_slide: "{{ source_slide_filename }}"
source_transcript: "{{ source_transcript_filename }}"
fact_check_passed: {{ fact_check_passed | lower }}
removed_claims: {{ removed_unsupported_claims }}
tags:
  - mba/aula
  - mba/{{ discipline_slug }}
---

# Aula {{ "%02d" | format(lesson_number) }}: {{ lesson_title }}

> [!info] Contexto da Disciplina
> Parte de [[01_Wiki_Disciplinas/{{ discipline_slug }}/_Indice_Materia|{{ discipline_name }}]] | Slide base: `{{ source_slide_filename }}`

<!-- AUTO-CONTENT:START -->
{{ body_markdown }}

## Conceitos Atomicos Relacionados
{% for zettel in extracted_zettels %}
- [[{{ zettel.slug }}|{{ zettel.title }}]]
{% endfor %}

## Conexoes Transversais no Curriculo
{% for link in cross_links %}
- [[01_Wiki_Disciplinas/{{ link.target_discipline_slug }}/_Indice_Materia|{{ link.target_discipline_name }}]]: {{ link.connection_summary }}
{% endfor %}

## Tensoes Dialeticas Identificadas
{% for tension in detected_tensions %}
- [[04_Diario_Tensoes/{{ tension.tension_slug }}|{{ tension.title }}]]: {{ tension.thesis }} vs. {{ tension.antithesis }}
{% endfor %}
<!-- AUTO-CONTENT:END -->

---
## Notas Pessoais de Aula
<!-- Espaco preservado em reprocessamentos -->
```

---

## 3. Nota Atomica no Zettelkasten (`02_Zettelkasten/<slug>.md`)
Localizacao: `02_Zettelkasten/<slug>.md`

Se o arquivo ja existir, o exportador preserva `content_markdown` e `domain_tags` existentes, une sem duplicatas novas tags em `tags` e acrescenta a aula atual na secao `## Referencias no Curso`.

O frontmatter e as anotacoes na secao de conexoes sao preservados; novas tags sao mescladas quando `tags` usa a lista em linhas do template. Formatos alternativos de tags nao sao reescritos. Na recuperacao de marcadores ausentes, o texto existente e mantido; marcadores duplicados ou invertidos bloqueiam a escrita.

```markdown
---
type: zettel
slug: "{{ slug }}"
title: "{{ title }}"
tags:
{% for tag in domain_tags %}
  - {{ tag }}
{% endfor %}
---

# {{ title }}

{{ content_markdown }}

## Conexoes Diretas
{% for link in related_links %}
- [[{{ link }}]]
{% endfor %}

## Referencias no Curso
<!-- AUTO-BACKLINKS:START -->
- [[Aula_{{ "%02d" | format(lesson_number) }}_{{ lesson_slug }}]] ({{ discipline_name }})
<!-- AUTO-BACKLINKS:END -->
```

---

## 4. Diario de Tensoes Dialeticas (`04_Diario_Tensoes/<tension_slug>.md`)
Localizacao: `04_Diario_Tensoes/<tension_slug>.md`

Se o arquivo ja existir, o exportador preserva o cabecalho conceitual e sintetico da tensao e acumula novas evidencias na secao `## Manifestacoes e Evidencias no Curso` de forma idempotente, resguardando tambem anotacoes pessoais.

Os blocos automaticos de conceitos e evidencias sao validados separadamente. Marcadores ausentes podem ser recuperados com `--force`, preservando o texto existente; pares duplicados, invertidos ou sobrepostos bloqueiam a escrita.

```markdown
---
type: tensao_dialetica
tension_slug: "{{ tension_slug }}"
title: "{{ title }}"
disciplines:
{% for disc in disciplines_involved %}
  - {{ disc }}
{% endfor %}
tags:
  - mba/tensao
---

# {{ title }}

## Tese vs Antitese
- **Tese:** {{ thesis }}
- **Antitese:** {{ antithesis }}

## Sintese e Paradoxo Estrategico
{{ synthesis_paradox }}

## Implicacoes Praticas de Negocio
{{ practical_implication }}

## Manifestacoes e Evidencias no Curso
<!-- AUTO-MANIFESTATIONS:START -->
- [[Aula_{{ "%02d" | format(lesson_number) }}_{{ lesson_slug }}]] ({{ discipline_name }})
<!-- AUTO-MANIFESTATIONS:END -->

---
## Notas Pessoais e Reflexoes
<!-- Espaco preservado em reprocessamentos -->
```

---

## 5. Indice do Diario de Tensoes (`04_Diario_Tensoes/_Indice_Tensoes.md`)
Localizacao: `04_Diario_Tensoes/_Indice_Tensoes.md`

Consolida todas as tensoes dialeticas rastreadas no cofre, gerado ou atualizado pelo comando `sync-tensions` ou ao fim de cada pipeline de aula.

Se faltarem marcadores, `--force` acrescenta um novo bloco preservando o texto existente. Pares duplicados ou invertidos bloqueiam a escrita.

```markdown
---
type: moc_tensoes
tags:
  - mba/moc
  - mba/tensoes
---

# Diario de Tensoes Dialeticas

MOC que consolida tensoes, trade-offs e conflitos estrategicos detectados transversalmente entre as disciplinas do curso.

<!-- AUTO-TENSIONS:START -->
{% for item in tensions %}
- [[{{ item.slug }}|{{ item.title }}]] (Disciplinas: {{ item.disciplines }})
{% endfor %}
<!-- AUTO-TENSIONS:END -->
```

---

## 6. Relatorio de Auditoria Factual (`03_Auditoria_Factual/<discipline_slug>_Aula_<NN>_audit.json`)
Localizacao: `03_Auditoria_Factual/<discipline_slug>_Aula_<NN>_audit.json`

Arquivo JSON salvo pelo `obsidian_writer.py` para cada execucao do pipeline, registrando o veredito de cada afirmacao auditada:

```json
{
  "discipline_slug": "{{ discipline_slug }}",
  "discipline_name": "{{ discipline_name }}",
  "lesson_number": 1,
  "lesson_title": "Titulo da Aula",
  "processed_date": "2026-11-07",
  "fact_check_passed": true,
  "source_transcript_filename": "Aula_01.mp4",
  "source_transcript_path": "C:/caminho/transcricoes/Aula_01.json",
  "source_transcript_binding": "explicit",
  "total_claims_audited": 12,
  "removed_unsupported_claims": 1,
  "audit_items": [
    {
      "claim_id": "CLM-001",
      "quote": "trecho exato da afirmacao",
      "category": "technical",
      "verdict": "verified",
      "severity": null,
      "evidence_source": "Slide 12 / Fala do professor min 14:20",
      "proposed_fix": null
    }
  ]
}
```

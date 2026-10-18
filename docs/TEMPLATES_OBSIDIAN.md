# Templates e Marcadores de Idempotencia do Obsidian

O modulo `src/mba_wiki/exporters/obsidian_writer.py` deve seguir estritamente estes formatos ao gerar ou atualizar arquivos no Vault.

---

## 1. Indice da Materia (`_Indice_Materia.md`)
Localizacao: `01_Wiki_Disciplinas/<discipline_slug>/_Indice_Materia.md`

Para garantir idempotencia ao adicionar novas aulas, o script deve substituir apenas o conteudo entre os marcadores `<!-- AUTO-LESSONS:START -->` e `<!-- AUTO-LESSONS:END -->`, preservando qualquer anotacao manual fora deles.

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

O corpo da aula (`body_markdown`) fica protegido entre marcadores automaticos. O bloco final de notas manuais nunca deve ser sobrescrito caso o arquivo ja exista no disco.

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
<!-- AUTO-CONTENT:END -->

---
## Notas Pessoais de Aula
<!-- Espaco preservado em reprocessamentos -->
```

---

## 3. Nota Atomica no Zettelkasten (`02_Zettelkasten/<slug>.md`)
Localizacao: `02_Zettelkasten/<slug>.md`

Se o arquivo ja existir, o exportador preserva `content_markdown` e `domain_tags` existentes, une sem duplicatas novas tags em `tags` e acrescenta a aula atual na secao `## Referencias no Curso`.

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

## 4. Relatorio de Auditoria Factual (`03_Auditoria_Factual/<discipline_slug>_Aula_<NN>_audit.json`)
Localizacao: `03_Auditoria_Factual/<discipline_slug>_Aula_<NN>_audit.json`

Arquivo JSON salvo pelo `obsidian_writer.py` para cada execucao do pipeline, registrando o veredito de cada afirmacao auditada:

```json
{
  "discipline_slug": "{{ discipline_slug }}",
  "discipline_name": "{{ discipline_name }}",
  "lesson_number": {{ lesson_number }},
  "lesson_title": "{{ lesson_title }}",
  "processed_date": "{{ processed_date }}",
  "fact_check_passed": {{ fact_check_passed | lower }},
  "total_claims_audited": {{ total_claims_audited }},
  "removed_unsupported_claims": {{ removed_unsupported_claims }},
  "audit_items": [
    {
      "claim_id": "CLM-001",
      "quote": "trecho exato da afirmacao",
      "category": "technical",
      "verdict": "verified",
      "severity": null,
      "evidence_source": "Slide 12",
      "proposed_fix": null
    }
  ]
}
```
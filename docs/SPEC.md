# Especificacao Tecnica: MBA Wiki Engine

## 1. Escopo e objetivo do sistema
Ferramenta CLI em Python para geracao automatizada de uma Wiki academica no Obsidian a partir de dois insumos primarios:
1. **Programa do Curso (Ementa):** Documento contendo a grade curricular, objetivos de cada disciplina, topicos por modulo e bibliografia oficial.
2. **Slides de Aula (PDF/PPTX):** Material apresentado pelo professor em cada encontro.

O sistema resolve o problema da compressao semantica de slides. Ele ancora os topicos curtos do slide na ementa oficial da disciplina, expande o conteudo em prosa didatica estruturada, audita os fatos gerados contra fontes primarias (`fact-check`) e aplica um filtro estilistico estrito (`humanizer-ptbr`) antes de persistir os arquivos Markdown puros no Obsidian.

## 2. Arquitetura do pipeline (Grafo de estados)
O processamento de uma aula ocorre em 5 estagios sequenciais com estado tipado:

1. **Ingestao e Ancoragem (`ingestion_node`):**
   - Extrai texto, tabelas e formulas matematicas (convertidas para LaTeX) do PDF/PPTX dos slides.
   - Localiza a disciplina e o modulo correspondentes no arquivo `ementa_estruturada.json`.
   - Produz o payload bruto pareado com as diretrizes curriculares e a bibliografia da materia.
2. **Redacao Hibrida Wiki + Zettel (`drafting_node`):**
   - Gera o rascunho da pagina da aula (`Aula_XX_Tema.md`) em formato de capitulo sequencial.
   - Identifica conceitos universais, teoremas ou modelos para criar ou vincular notas atomicas (`[[WikiLinks]]`) na pasta de Zettelkasten.
3. **Auditoria Factual Adversarial (`fact_check_node`):**
   - Extrai todas as afirmacoes objetivas (datas, formulas, autores, premissas, metricas) do rascunho expandido.
   - Confronta cada afirmacao contra o conteudo literal dos slides e a bibliografia da ementa.
   - Classifica desvios de S1 a S6: corrige imprecisoes e erros factuais (S1/S2) e remove afirmacoes sem lastro verificavel (S4), contabilizando `removed_unsupported_claims`.
   - Registra desvios conceituais/logicos (S3/S5) e imprecisoes menores (S6) em `ClaimAuditItem`.
   - Define `fact_check_passed = True` se todas as afirmacoes forem verificadas ou devidamente corrigidas/removidas sem violacoes graves pendentes (S1, S3, S5 sem solucao).
4. **Linter Estilistico (`humanizer_node`):**
   - Reescreve a prosa (`body_markdown` e `content_markdown`) seguindo as diretrizes do `docs/LINTER_RULES.md`.
   - Executa validacao deterministica via codigo (`validators.py`).
   - Se houver violacoes, realimenta os erros a LLM em ate 3 tentativas de autocorrecao; se persistirem erros apos a 3ª tentativa, lanca `ValidationError` interrompendo o pipeline para evitar gravacao corrompida no Vault.
5. **Persistencia na Wiki (`persistence_node`):**
   - Grava a pagina da aula na pasta da respectiva disciplina no Obsidian.
   - Atualiza o arquivo `_Indice_Materia.md` (MOC da disciplina) de forma idempotente.
   - Grava as notas atômicas novas na pasta `02_Zettelkasten/`.

## 3. Contratos de dados (Schemas Pydantic v2)

```python
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class SyllabusModule(BaseModel):
    discipline_slug: str
    discipline_name: str
    professor: str | None = None
    syllabus_summary: str
    topics: list[str]
    bibliography: list[str]


class SlideChunk(BaseModel):
    slide_number: int
    title: str
    raw_text: str
    latex_equations: list[str] = Field(default_factory=list)
    visual_descriptions: list[str] = Field(default_factory=list)


class ClaimAuditItem(BaseModel):
    claim_id: str
    quote: str
    category: Literal["formula", "date", "attribution", "technical", "metric"]
    verdict: Literal["verified", "false", "imprecise", "misleading", "unsupported"]
    severity: Literal["S1", "S2", "S3", "S4", "S5", "S6"] | None = None
    evidence_source: str | None = None
    proposed_fix: str | None = None


class AtomicZettel(BaseModel):
    slug: str
    title: str
    domain_tags: list[str]
    content_markdown: str
    related_links: list[str]


class WikiLessonOutput(BaseModel):
    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    lesson_slug: str
    processed_date: date
    source_slide_filename: str
    fact_check_passed: bool
    removed_unsupported_claims: int
    body_markdown: str
    extracted_zettels: list[AtomicZettel]
    audit_items: list[ClaimAuditItem] = Field(default_factory=list)


class LessonAuditReport(BaseModel):
    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    processed_date: date
    fact_check_passed: bool
    total_claims_audited: int
    removed_unsupported_claims: int
    audit_items: list[ClaimAuditItem] = Field(default_factory=list)


class StructuredSyllabus(BaseModel):
    modules: list[SyllabusModule]


class LessonPipelineState(BaseModel):
    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    lesson_slug: str
    source_slide_filename: str
    slides: list[SlideChunk]
    syllabus: SyllabusModule
    raw_draft: str | None = None
    extracted_zettels: list[AtomicZettel] = Field(default_factory=list)
    audit_items: list[ClaimAuditItem] = Field(default_factory=list)
    fact_check_passed: bool = False
    removed_unsupported_claims: int = 0
    audited_markdown: str | None = None
    humanized_markdown: str | None = None
    humanizer_retry_count: int = 0
    output: WikiLessonOutput | None = None
```

## 4. Topologia de diretorios no Obsidian Vault

```plaintext
vault_mba/
├── 00_Programa_Curso/
│   ├── Dashboard_MBA.md
│   └── ementa_estruturada.json
├── 01_Wiki_Disciplinas/
│   └── <discipline_slug>/
│       ├── _Indice_Materia.md
│       └── Aula_<NN>_<slug_tema>.md
├── 02_Zettelkasten/
│   └── <zettel_slug>.md
└── 03_Auditoria_Factual/
    └── <discipline_slug>_Aula_<NN>_audit.json
```
# Especificacao Tecnica: MBA Wiki Engine

## 1. Escopo e objetivo do sistema
Ferramenta CLI em Python para geracao automatizada de uma Wiki academica no Obsidian a partir de tres insumos primarios:
1. **Programa do Curso (Ementa):** Documento contendo a grade curricular, objetivos de cada disciplina, topicos por modulo e bibliografia oficial.
2. **Slides de Aula (PDF/PPTX):** Material apresentado pelo professor em cada encontro.
3. **Transcricoes de Videoaulas (JSON opcional):** Registros literais e saneados de fala gerados a partir dos videos das aulas pelo motor de transcricao desacoplado (`transcribe-batch`).

O sistema resolve o problema da compressao semantica de slides e oratoria fragmentada. Ele ancora os topicos dos slides e a fala do professor na ementa oficial da disciplina, expande o conteudo em prosa didatica estruturada, sintetiza tensoes dialeticas interdisciplinares, audita os fatos gerados contra fontes primarias (`fact-check`), purga afirmacoes sem suporte ou zettels/tensoes corrompidos e aplica um filtro estilistico estrito (`humanizer-ptbr`) antes de persistir os arquivos Markdown puros no Obsidian de forma idempotente.

## 2. Arquitetura do pipeline (Grafo de estados)
O processamento de uma aula ocorre em 5 estagios sequenciais com estado tipado:

1. **Ingestao e Ancoragem (`ingestion_node`):**
   - Extrai texto, tabelas e formulas matematicas (convertidas para LaTeX) do PDF/PPTX dos slides.
   - Carrega opcionalmente a transcricao da videoaula correspondente (`VideoTranscript`), seja por caminho explicito ou auto-deteccao em `data/raw/transcripts/`.
   - Localiza a disciplina e o modulo correspondentes no arquivo `ementa_estruturada.json`.
   - Carrega o curriculo global (`StructuredSyllabus`) para viabilizar conexoes transversais.
   - Produz o payload bruto pareado com as diretrizes curriculares e a bibliografia da materia.
2. **Redacao Hibrida Wiki, Zettel e Conexoes Transversais (`drafting_node`):**
   - Gera o rascunho da pagina da aula (`Aula_XX_Tema.md`) em formato de capitulo sequencial, fundindo a estrutura do slide com a explicacao oral da videoaula quando disponivel.
   - Identifica conceitos universais, teoremas ou modelos para criar ou vincular notas atomicas (`[[WikiLinks]]`) na pasta de Zettelkasten.
   - Analisa tensoes dialeticas e trade-offs interdisciplinares entre a materia atual e outras disciplinas da ementa (`DialecticalTension` e `CrossDisciplineLink`).
3. **Auditoria Factual Adversarial (`fact_check_node`):**
   - Extrai todas as afirmacoes objetivas (datas, formulas, autores, premissas, metricas) do rascunho expandido.
   - Confronta cada afirmacao contra o conteudo literal dos slides, a transcricao de fala do professor e a bibliografia da ementa.
   - Classifica desvios de S1 a S6: corrige imprecisoes e erros factuais (S1/S2) e remove afirmacoes sem lastro verificavel (S4), contabilizando `removed_unsupported_claims`.
   - Audita o corpo da aula, os Zettels atomicos candidatos e as tensoes dialeticas identificadas, expurgando zettels e tensoes contaminados por declaracoes falsas (`S1`) ou sem lastro (`S4`).
   - Bloqueia o avanco do pipeline (`has_unresolved_blockers = True`) caso correcoes essenciais nao tenham sido aplicadas com sucesso no texto.
   - Em caso de bloqueio, interrompe antes do Humanizer e grava o relatorio em `03_Auditoria_Factual/pendentes/`, sem alterar a aula publicada nem sua auditoria aprovada.
   - Registra desvios conceituais/logicos (S3/S5) e imprecisoes menores (S6) em `ClaimAuditItem`.
   - Define `fact_check_passed = True` se todas as afirmacoes forem verificadas ou devidamente corrigidas/removidas sem violacoes graves pendentes.
4. **Linter Estilistico (`humanizer_node`):**
   - Aplica pre-sanitizacao deterministica em Python para Zettels atomicos, eliminando retentativas excessivas e chamadas repetidas N+1 a LLM.
   - Reescreve a prosa (`body_markdown` e `content_markdown`) seguindo as diretrizes do `docs/LINTER_RULES.md`, protegendo cercas e blocos legitimos de codigo Markdown.
   - Executa validacao deterministica via codigo (`validators.py`).
   - Se houver violacoes, realimenta os erros a LLM em ate 3 tentativas de autocorrecao; se persistirem erros apos a 3ª tentativa, lanca `ValidationError` interrompendo o pipeline para evitar gravacao corrompida no Vault.
   - Apos a reescrita, executa nova auditoria sobre o corpo final, Zettels e tensoes. Qualquer desvio factual apontado nessa verificacao bloqueia a publicacao e gera relatorio pendente, mesmo se houver correcao sugerida; os vereditos registram a etapa `draft` ou `final`.
5. **Persistencia na Wiki e Recuperacao no Obsidian (`persistence_node`):**
   - Grava a pagina da aula na pasta da respectiva disciplina no Obsidian, preservando notas manuais do usuario fora dos delimitadores de conteudo.
   - Atualiza o arquivo `_Indice_Materia.md` (MOC da disciplina) de forma idempotente sem duplicatas.
   - Grava as notas atomicas novas ou atualizadas na pasta `02_Zettelkasten/`.
   - Grava ou atualiza notas de tensao dialetica em `04_Diario_Tensoes/<tension_slug>.md` e consolida o `_Indice_Tensoes.md`.
   - Oferece auto-recuperacao de delimitadores estruturais corrompidos caso o arquivo tenha sido adulterado manualmente.

## 3. Contratos de dados (Schemas Pydantic v2)

```python
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator


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
    audit_stage: Literal["draft", "final"] = "draft"


class AtomicZettel(BaseModel):
    slug: str
    title: str
    domain_tags: list[str]
    content_markdown: str
    related_links: list[str]


class CrossDisciplineLink(BaseModel):
    target_discipline_slug: str
    target_discipline_name: str
    connection_summary: str
    epistemic_conflict: str | None = None


class DialecticalTension(BaseModel):
    tension_slug: str
    title: str
    disciplines_involved: list[str]
    thesis: str
    antithesis: str
    synthesis_paradox: str
    practical_implication: str


class TranscriptSegment(BaseModel):
    id: int
    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)
    text_raw: str
    text_cleaned: str

    @model_validator(mode="after")
    def validate_timestamp_interval(self) -> "TranscriptSegment":
        if self.end < self.start:
            raise ValueError(f"End timestamp ({self.end}) cannot be less than start ({self.start})")
        return self


class VideoTranscript(BaseModel):
    source_filename: str
    discipline_slug: str
    duration_seconds: float = Field(..., ge=0.0)
    model_name: str
    compute_type: str
    processed_at: datetime
    full_text_raw: str
    full_text_cleaned: str
    segments: list[TranscriptSegment] = Field(default_factory=list)


class WikiLessonOutput(BaseModel):
    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    lesson_slug: str
    processed_date: date
    source_slide_filename: str
    source_transcript_filename: str | None = None
    fact_check_passed: bool
    removed_unsupported_claims: int
    body_markdown: str
    extracted_zettels: list[AtomicZettel]
    cross_links: list[CrossDisciplineLink] = Field(default_factory=list)
    detected_tensions: list[DialecticalTension] = Field(default_factory=list)
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
    transcript: VideoTranscript | None = None
    syllabus: SyllabusModule
    full_syllabus: StructuredSyllabus | None = None
    raw_draft: str | None = None
    extracted_zettels: list[AtomicZettel] = Field(default_factory=list)
    cross_links: list[CrossDisciplineLink] = Field(default_factory=list)
    detected_tensions: list[DialecticalTension] = Field(default_factory=list)
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
├── 03_Auditoria_Factual/
│   └── <discipline_slug>_Aula_<NN>_audit.json
└── 04_Diario_Tensoes/
    ├── _Indice_Tensoes.md
    └── <tension_slug>.md
```

# Especificacao Tecnica: Cathedra

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
   - Carrega opcionalmente a transcricao da videoaula (`VideoTranscript`). A selecao automatica exige `discipline_slug` e `lesson_number` correspondentes e uma candidata inequivoca; diante de candidatas ambiguas ou arquivos nao identificados junto de uma candidata, exige `--transcript`.
   - Um caminho explicito inexistente ou invalido, uma disciplina divergente ou um numero de aula conflitante interrompem o processamento. Para transcricoes antigas sem `lesson_number`, a escolha explicita declara a associacao e nao comprova o conteudo do video.
   - Registra o nome do video, o caminho absoluto do JSON e a forma de associacao nos relatorios factuais aprovados e pendentes.
   - Localiza a disciplina e o modulo correspondentes no arquivo `ementa_estruturada.json`.
   - Carrega o curriculo global (`StructuredSyllabus`) para viabilizar conexoes transversais.
   - Produz o payload bruto pareado com as diretrizes curriculares e a bibliografia da materia.
2. **Redacao Hibrida Wiki, Zettel e Conexoes Transversais (`drafting_node`):**
   - Gera o rascunho da pagina da aula (`Aula_XX_Tema.md`) em formato de capitulo sequencial, fundindo a estrutura do slide com a explicacao oral da videoaula quando disponivel.
   - Identifica conceitos universais, teoremas ou modelos para criar ou vincular notas atomicas (`[[WikiLinks]]`) na pasta de Zettelkasten.
   - Analisa tensoes dialeticas e trade-offs interdisciplinares entre a materia atual e outras disciplinas da ementa (`DialecticalTension` e `CrossDisciplineLink`).
3. **Guardrail Anti-Alucinacao (`fact_check_node`):**
   - Opera em **passada unica** usando o schema enxuto `GuardrailResponse` (`issues: list[GuardrailIssue]`), focado exclusivamente em impedir erros materiais graves (`S1`/`S5`) e alucinacoes reais (`S4`), sem executar auditoria forense citacao a citacao.
   - Usa como referencias exclusivas o conteudo extraido dos slides (PDF/PPTX) e a transcricao da fala do professor; o resumo e os topicos da ementa situam apenas o escopo da disciplina, e a bibliografia da ementa nao e injetada nem conta como obra consultada.
   - Explicacoes didaticas corretas, parafrases fieis e definicoes conceituais consolidadas da area retornam `issues: []` e nao bloqueiam o fluxo.
   - Corrige erros materiais (`S1`/`S2`/`S3`/`S5`) quando `proposed_fix` e fornecido e remove alucinacoes (`S4`) preservando indentacao de blocos de codigo e listas; observacoes `S2`/`S6` sem `proposed_fix` sao registradas sem bloqueio duro.
   - Filtra e remedia `extracted_zettels` e `detected_tensions` sobre copias defensivas (sem mutacao in-place), expurgando itens contaminados por `S1`/`S4` nao resolvidos.
   - Bloqueia o avanco do pipeline (`FactCheckBlockedError`) antes do Humanizer e grava o relatorio em `03_Auditoria_Factual/pendentes/` quando restarem erros criticos (`S1`/`S5`) ou alucinacoes nao resolvidas. Com `--allow-pending-review`, pendencias nao criticas podem publicar marcadas como `pending_review`, mas erros criticos `S1`/`S5` (inclusive orfaos ou em Zettels/Tensoes) permanecem bloqueados.
4. **Linter Estilistico e Invariancia Pos-Humanizador (`humanizer_node` + `audit_humanized_invariance`):**
   - Normaliza sequencias literais `\n` fora de codigo/LaTeX na fronteira de `DraftResult` e aplica pre-sanitizacao deterministica mascarada (`sanitize_markdown_heuristics`) preservando codigo, LaTeX e faixas numericas (`2020-2024`).
   - Reescreve a prosa (`body_markdown` e Zettels com violacoes) seguindo `docs/LINTER_RULES.md`, sem fallback para `raw_draft` nao auditado.
   - Executa validacao deterministica via `validators.py` (incluindo `R5_LITERAL_NEWLINE`); em caso de violacoes, reenvia o feedback ancorado no `audited_markdown` original em ate 3 tentativas, lancando `HumanizerValidationError` se nao convergir.
   - Apos a reescrita, executa verificacao de invariancia (`audit_humanized_invariance`) comparando `audited_markdown` vs. `humanized_markdown` e pares antes/depois apenas para Zettels efetivamente alterados pelo Humanizer; desvios criticos bloqueiam a publicacao e gravam relatorio pendente.
5. **Persistencia na Wiki e Recuperacao no Obsidian (`persistence_node`):**
   - Grava a pagina da aula na pasta da respectiva disciplina no Obsidian, preservando notas manuais do usuario fora dos delimitadores `AUTO-CONTENT` e exportando Zettels relacionados e `cross_links` (`## Conexoes Transversais no Curriculo`).
   - Atualiza seletivamente as chaves gerenciadas de auditoria no frontmatter da aula (`processed_date`, `fact_check_passed`, `fact_check_status`, `removed_claims`) em reprocessamentos, preservando chaves personalizadas e notas manuais.
   - Atualiza o arquivo `_Indice_Materia.md` (MOC da disciplina) de forma idempotente sem duplicatas.
   - Grava notas atomicas em `02_Zettelkasten/` com delimitadores `AUTO-CONTENT` e `AUTO-BACKLINKS`; reprocessar com `--force` permite atualizar o corpo de Zettels existentes (inclusive legados com `type: zettel`) preservando tags, conexoes diretas e backlinks.
   - Grava ou atualiza notas de tensao dialetica em `04_Diario_Tensoes/<tension_slug>.md`, consolida `_Indice_Tensoes.md` e persiste `LessonAuditReport` (incluindo `has_pending_review`) em `03_Auditoria_Factual/`.
   - O exportador prepara todos os artefatos fora do cofre e, em caso de erro na substituicao, tenta restaurar os arquivos ja modificados sem sobrescrever edicoes concorrentes.

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
    evidence_kind: Literal["slide", "transcript", "syllabus"] | None = None
    evidence_locator: int | None = None
    evidence_quote: str | None = None
    evidence_status: Literal["material_supported", "pending_review"] = "pending_review"


class GuardrailIssue(BaseModel):
    claim_id: str
    quote: str
    category: Literal["formula", "date", "attribution", "technical", "metric"]
    verdict: Literal["false", "imprecise", "misleading", "unsupported"]
    severity: Literal["S1", "S2", "S3", "S4", "S5", "S6"]
    reason: str | None = None
    proposed_fix: str | None = None


class GuardrailResponse(BaseModel):
    issues: list[GuardrailIssue] = Field(default_factory=list)


class AtomicZettel(BaseModel):
    slug: str
    title: str
    domain_tags: list[str]
    content_markdown: str
    related_links: list[str]


class CrossDisciplineLink(BaseModel):
    target_discipline_slug: str
    target_topic: str
    connection_type: Literal["prerequisite", "impact", "contrast", "synergy"]
    description: str


class DialecticalTension(BaseModel):
    slug: str
    title: str
    pole_a_discipline: str
    pole_a_framework: str
    pole_a_thesis: str
    pole_b_discipline: str
    pole_b_framework: str
    pole_b_thesis: str
    tension_nature: str
    synthesis_guidelines: str
    related_zettel_slugs: list[str] = Field(default_factory=list)


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


class TranscriptCheckpoint(BaseModel):
    source_relative_path: str
    source_size_bytes: int
    source_sha256: str
    model_name: str
    device: str
    compute_type: str
    language: str
    vad_filter: bool
    beam_size: int
    engine_version: str
    pipeline_revision: str


class VideoTranscript(BaseModel):
    source_filename: str
    discipline_slug: str
    lesson_number: int | None = Field(default=None, gt=0, strict=True)
    duration_seconds: float = Field(..., ge=0.0)
    model_name: str
    compute_type: str
    processed_at: datetime
    full_text_raw: str
    full_text_cleaned: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    checkpoint: TranscriptCheckpoint | None = None


class WikiLessonOutput(BaseModel):
    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    lesson_slug: str
    processed_date: date
    source_slide_filename: str
    source_transcript_filename: str | None = None
    source_transcript_path: str | None = None
    source_transcript_binding: Literal["explicit", "auto", "in_memory"] | None = None
    fact_check_passed: bool
    has_pending_review: bool = False
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
    has_pending_review: bool = False
    total_claims_audited: int
    removed_unsupported_claims: int
    audit_items: list[ClaimAuditItem] = Field(default_factory=list)
    source_transcript_filename: str | None = None
    source_transcript_path: str | None = None
    source_transcript_binding: Literal["explicit", "auto", "in_memory"] | None = None


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
    source_transcript_path: str | None = None
    source_transcript_binding: Literal["explicit", "auto", "in_memory"] | None = None
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

## 5. Orquestração Sequencial por Disciplina (`build-discipline`)

- O comando `build-discipline <discipline_slug>` (ou `--all` para percorrer toda a grade) lê `ementa_estruturada.json` e executa as aulas em ordem numérica crescente a partir dos slides em `data/raw/slides/<discipline_slug>/`.
- No modo `--all`, as disciplinas seguem estritamente a ordem em que aparecem em `StructuredSyllabus.modules`.
- Slides com numeração duplicada bloqueiam a execução antes do início do pipeline; quando uma aula falha na auditoria factual (`FactCheckBlockedError`), a sequência é interrompida preservando as aulas já exportadas e gravando o relatório pendente.

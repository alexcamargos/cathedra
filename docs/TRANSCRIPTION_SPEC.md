# Especificação Técnica: Motor de Transcrição e Ingestão de Áudio Desacoplado

## 1. Escopo e Objetivo
Módulo utilitário e autônomo para extração de áudio, transcrição literal acelerada por GPU e saneamento de disfluências a partir de videoaulas em formato MP4.

O módulo atua como pré-processador da camada bruta (*raw*), gerando artefatos JSON estruturados com timestamps por segmento e texto limpo. Ele não se acopla ao grafo de execução da Wiki em tempo real, permitindo processamento noturno em lote.

---

## 2. Topologia de Dados e Diretórios

Seguindo a arquitetura em camadas (Medallion):
* **Entrada (Vídeos originais):** Diretório externo ou local contendo videoaulas em MP4 organizadas por disciplina:
  ```text
  <caminho_videos>/
  └── <discipline_slug>/
      ├── Aula_01_Tema.mp4
      └── Aula_02_Tema.mp4
  ```
* **Saída (Camada Bruta / Raw Transcripts):**
  ```text
  data/raw/transcripts/
  └── <discipline_slug>/
      ├── Aula_01_Tema.json
      └── Aula_02_Tema.json
  ```
* **Arquivos Voláteis:** Arquivos de áudio intermediários (`.wav` 16kHz mono) são gerados em diretório temporário de scratch e expurgados imediatamente após a transcrição do arquivo correspondente.

---

## 3. Contratos de Dados (Pydantic v2)

```python
from datetime import datetime
from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """Segmento temporal de transcrição com delimitação em segundos."""

    id: int
    start: float = Field(..., description="Início do segmento em segundos")
    end: float = Field(..., description="Fim do segmento em segundos")
    text_raw: str = Field(..., description="Texto literal transcrito pelo modelo")
    text_cleaned: str = Field(..., description="Texto saneado sem marcadores discursivos vazios")


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
    """Artefato consolidado de transcrição de uma videoaula."""

    source_filename: str
    discipline_slug: str
    lesson_number: int | None = Field(default=None, gt=0, strict=True)
    duration_seconds: float
    model_name: str
    compute_type: str
    processed_at: datetime
    full_text_raw: str
    full_text_cleaned: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    checkpoint: TranscriptCheckpoint | None = None
```

O campo `lesson_number` e opcional para compatibilidade com transcricoes existentes. O lote nao o infere automaticamente do nome do video. Para vincular uma transcricao sem esse campo, informe seu JSON explicitamente em `build-lesson --transcript`; a escolha explicita declara a associacao com a aula. A busca automatica somente usa transcricoes com disciplina e numero da aula preenchidos e correspondentes.

---

## 4. Arquitetura dos Componentes

### 4.1. Auto-Provisão de Ambiente (`bootstrap.py`)
1. **FFmpeg:**
   - Verifica `shutil.which("ffmpeg")`.
   - Se ausente, busca em `%LOCALAPPDATA%\cathedra\bin\ffmpeg.exe`.
   - Se inexistente, efetua download automático do pacote estático oficial (build minimal para Windows x64), extrai o binário e o injeta dinamicamente em `os.environ["PATH"]`.
2. **CUDA & cuDNN (Windows):**
   - Localiza os caminhos de DLL dos pacotes oficiais NVIDIA no virtualenv (`site-packages/nvidia/cublas/bin`, `site-packages/nvidia/cudnn/bin`).
   - Registra os diretórios via `os.add_dll_directory()` antes de carregar o `ctranslate2`.
   - Valida se `ctranslate2.get_cuda_device_count() > 0`. Caso não haja suporte CUDA operacional, emite alerta e configura fallback transparente para CPU.

### 4.2. Extrator de Áudio (`audio_extractor.py`)
- Invoca o binário do FFmpeg via subprocess para extrair trilha de áudio:
  - Formato: PCM 16-bit (`pcm_s16le`).
  - Taxa de amostragem: 16.000 Hz (`-ar 16000`).
  - Canal: Mono (`-ac 1`).
  - Omissão de trilha de vídeo (`-vn`).

### 4.3. Normalizador Determinístico de Disfluências (`cleaner.py`)
- Expressões regulares compiladas e regras léxicas determinísticas para saneamento de fala em português do Brasil:
  - Hesitações isoladas: `"é..."`, `"ah..."`, `"hum..."`, `"eh"`, `"hã"`.
  - Muletas conversacionais em início/fim de oração: `"né?"`, `"tá?"`, `"sabe?"`, `"tipo assim"`.
  - Gagueiras e repetições imediatas de conectivos e artigos: `"o o" -> "o"`, `"de de" -> "de"`, `"que que" -> "que"`.
  - Preservação estrita de termos técnicos, jargões, números e datas.

### 4.4. Motor de Transcrição (`transcriber.py`)
- Encapsula `faster-whisper.WhisperModel`.
- Parâmetros canônicos de inferência:
  - `model_size_or_path`: `"large-v3"` (ou configurável via CLI).
  - `device`: `"cuda"` (fallback `"cpu"`).
  - `compute_type`: `"int8_float16"` em GPU (ou `"int8"` em CPU).
  - `vad_filter`: `True` (Silero VAD para expurgar silêncios e ruídos de fundo).
  - `language`: `"pt"`.

### 4.5. Pipeline em Lote com Checkpoint (`batch_runner.py`)
- Varre a pasta raiz informada, detectando subpastas por disciplina.
- Antes de iniciar o transcritor, rejeita o lote quando dois videos apontam para o mesmo destino, inclusive com `--force`.
- Reutiliza um JSON apenas se o checkpoint registrar caminho relativo, tamanho e SHA-256 do video e os parametros efetivos correspondentes: nome do modelo, dispositivo, precisao, idioma, VAD, beam size, versao do faster-whisper e revisao do pipeline.
- Videos ou configuracoes alterados sao reprocessados, e o JSON anterior e preservado em `.history/<disciplina>/`; o caminho da copia e informado no progresso e na telemetria. O nome do modelo e a versao da biblioteca nao comprovam que os pesos remotos ou arquivos locais do modelo permaneceram identicos.
- JSONs antigos sem checkpoint ou invalidos sao relatados como nao verificados e preservados. `--force` autoriza reprocessa-los com copia anterior; um JSON que identifique outro video, disciplina ou caminho de origem e tratado como colisao, mesmo com `--force`.
- Revalida o hash do video apos a transcricao e verifica se o JSON foi alterado antes de substitui-lo. Sem um bloqueio entre processos, nao ha garantia absoluta contra edicoes concorrentes no intervalo final de gravacao.
- O lote nao migra automaticamente JSONs antigos. A funcao de migracao separada rejeita lotes com colisoes antes de mover arquivos.
- A revisao do pipeline deve ser incrementada quando mudarem os parametros de extracao, inferencia ou limpeza que influenciam o resultado.
- Registra logs detalhados de tempo decorrido, taxa de aceleração em relação ao tempo real e consumo de VRAM.


### 4.6. Vinculação em Lote à Ementa (`binder.py`)
- Lê `ementa_estruturada.json` e pareia subpastas de `data/raw/transcripts/` com os `discipline_slug` oficiais da ementa, corrigindo slugs legados sem invalidar o `checkpoint` existente.
- Extrai `lesson_number` pelo prefixo numérico do nome do arquivo, rejeitando numerações duplicadas (ambíguas) ou ausentes e reportando pastas fora da grade regular (como `palestras`) e divergências com `data/raw/slides/`.
- Suporta simulação com `--dry-run` e grava alterações atomicamente preservando histórico em `.history/<disciplina>/`.

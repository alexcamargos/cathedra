"""Command line interface (CLI) for the MBA Wiki Engine using Typer.

Exposes primary entrypoint commands:
- init-syllabus: Parses and persists structured syllabus from course program documents.
- build-lesson: Processes presentation slides through the full drafting, auditing,
  and humanizing pipeline, exporting markdown wiki pages and zettels to Obsidian.
"""

import contextlib
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Annotated

# Force UTF-8 encoding on standard output/error to prevent mojibake in Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    with contextlib.suppress(Exception):
        sys.stderr.reconfigure(encoding="utf-8")

import typer

from mba_wiki.agents.graph import (
    FactCheckBlockedError,
    find_syllabus_module,
    ingestion_node,
    run_lesson_pipeline,
    slugify,
)
from mba_wiki.agents.llm_client import StructuredLLMClient, create_llm_client
from mba_wiki.config import get_settings
from mba_wiki.exporters.obsidian_writer import (
    export_lesson_to_vault,
    write_blocked_audit_report,
    write_tensions_index,
)
from mba_wiki.ingestion.syllabus_parser import (
    load_structured_syllabus,
    process_and_save_syllabus,
)
from mba_wiki.schemas import DialecticalTension
from mba_wiki.transcription.batch_runner import (
    ProgressEvent,
    migrate_legacy_transcripts,
    run_transcription_batch,
)
from mba_wiki.transcription.telemetry import TranscriptionLogger
from mba_wiki.transcription.transcriber import LectureTranscriber

app = typer.Typer(
    name="mba-wiki",
    help="MBA Wiki Engine: automação de notas acadêmicas no Obsidian.",
    no_args_is_help=True,
)

_client_override: StructuredLLMClient | None = None


def set_client_override(client: StructuredLLMClient | None) -> None:
    """Sets a global client override for testing or custom dependency injection.

    Args:
        client: Implementation conforming to StructuredLLMClient, or None to reset.

    Returns:
        None.

    Raises:
        None.
    """
    global _client_override
    _client_override = client


def get_client(auditor: bool = False) -> StructuredLLMClient:
    """Resolves and returns the active StructuredLLMClient instance.

    Args:
        auditor: Whether to resolve the specialized model for factual auditing.

    Returns:
        Configured StructuredLLMClient implementation.

    Raises:
        ValueError: If client cannot be initialized or API key is missing.
    """
    if _client_override is not None:
        return _client_override
    settings = get_settings()
    model = settings.llm_model_auditor if auditor else settings.llm_model_drafter
    return create_llm_client(
        api_key=settings.gemini_api_key,
        model=model,
        backend=settings.llm_backend,
    )


@app.command(name="init-syllabus")
def init_syllabus(
    source_file: Annotated[
        Path,
        typer.Argument(
            help="Caminho para o documento do Programa do Curso (PDF, TXT ou MD).",
            exists=False,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    destination: Annotated[
        Path | None,
        typer.Option(
            "--destination",
            "-d",
            help="Caminho explícito de destino para o arquivo ementa_estruturada.json.",
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    vault: Annotated[
        Path | None,
        typer.Option(
            "--vault",
            "-v",
            help="Caminho base do Obsidian Vault (sobrescreve configuração padrão).",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Estrutura a ementa do curso e salva ementa_estruturada.json no Obsidian Vault.

    Args:
        source_file: Caminho do arquivo da ementa a ser estruturado.
        destination: Caminho opcional explícito para salvar o JSON.
        vault: Caminho opcional do Vault do Obsidian.

    Returns:
        None.

    Raises:
        typer.Exit: Com código 1 em caso de erro de arquivo ou processamento.
    """
    if not source_file.is_file():
        typer.echo(f"Erro: Arquivo de ementa não encontrado: {source_file}", err=True)
        raise typer.Exit(code=1)

    settings = get_settings()
    vault_root = vault or settings.obsidian_vault_path
    target_json = destination or (vault_root / "00_Programa_Curso" / "ementa_estruturada.json")

    try:
        client = get_client()
        process_and_save_syllabus(
            source_path=source_file,
            destination_path=target_json,
            client=client,
        )
        typer.echo(f"Ementa estruturada gerada com sucesso em: {target_json}")
    except Exception as exc:
        typer.echo(f"Erro ao processar ementa: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command(name="build-lesson")
def build_lesson(
    slide_path: Annotated[
        Path,
        typer.Argument(
            help="Caminho para a apresentação de slides da aula (PDF ou PPTX).",
            exists=False,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    discipline: Annotated[
        str,
        typer.Option(
            "--discipline",
            "-d",
            help="Slug identificador da disciplina (ex: financas-corporativas).",
        ),
    ],
    lesson: Annotated[
        int,
        typer.Option(
            "--lesson",
            "-l",
            help="Número sequencial da aula na disciplina.",
            min=1,
        ),
    ],
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            "-t",
            help="Título temático da aula (se omitido, será inferido dos slides).",
        ),
    ] = None,
    slug: Annotated[
        str | None,
        typer.Option(
            "--slug",
            "-s",
            help="Slug customizado para o arquivo da aula.",
        ),
    ] = None,
    vault: Annotated[
        Path | None,
        typer.Option(
            "--vault",
            "-v",
            help="Caminho do Obsidian Vault (sobrescreve configuração).",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    syllabus_json: Annotated[
        Path | None,
        typer.Option(
            "--syllabus-json",
            help="Caminho explícito para ementa_estruturada.json.",
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    transcript: Annotated[
        Path | None,
        typer.Option(
            "--transcript",
            "-t",
            help="Caminho explícito para a transcrição da aula em formato JSON.",
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Força reprocessamento e recupera delimitadores HTML corrompidos no cofre.",
        ),
    ] = False,
) -> None:
    """Executa o pipeline completo de uma aula e exporta os arquivos para o Obsidian Vault.

    Args:
        slide_path: Caminho para a apresentação da aula em PDF ou PPTX.
        discipline: Slug da disciplina correspondente na ementa.
        lesson: Número da aula dentro da disciplina.
        title: Título opcional da aula.
        slug: Slug opcional da aula.
        vault: Caminho opcional do Obsidian Vault.
        syllabus_json: Caminho opcional para ementa_estruturada.json.
        transcript: Caminho opcional para a transcrição da videoaula em formato JSON.
        force: Força reprocessamento de arquivos e delimitações.

    Returns:
        None.

    Raises:
        typer.Exit: Com código 1 em caso de arquivo inexistente ou erro no pipeline.
    """
    if not slide_path.is_file():
        typer.echo(f"Erro: Arquivo de slides não encontrado: {slide_path}", err=True)
        raise typer.Exit(code=1)

    settings = get_settings()
    vault_root = vault or settings.obsidian_vault_path
    vault_root.mkdir(parents=True, exist_ok=True)

    target_syllabus_json = syllabus_json or (
        vault_root / "00_Programa_Curso" / "ementa_estruturada.json"
    )
    if not target_syllabus_json.is_file():
        typer.echo(
            f"Erro: Ementa estruturada não encontrada em {target_syllabus_json}. "
            "Execute 'init-syllabus' primeiro.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        structured_syllabus = load_structured_syllabus(target_syllabus_json)
        module = find_syllabus_module(structured_syllabus, discipline)
    except KeyError as err:
        typer.echo(
            f"Erro: Disciplina '{discipline}' não encontrada na ementa.",
            err=True,
        )
        raise typer.Exit(code=1) from err
    except Exception as exc:
        typer.echo(f"Erro ao carregar ementa: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        resolved_slug = slug or (slugify(title) if title else None)

        # Resolução de transcrição de fala (explícita ou auto-detecção em data/raw/transcripts)
        resolved_transcript_path: Path | None = transcript
        if resolved_transcript_path is None:
            candidate_paths = [
                Path("data/raw/transcripts") / discipline / f"{slide_path.stem}.json",
                Path("data/raw/transcripts") / "geral" / f"{slide_path.stem}.json",
                Path("data/raw/transcripts") / discipline / f"Aula_{lesson:02d}.json",
            ]
            for candidate in candidate_paths:
                if candidate.is_file():
                    resolved_transcript_path = candidate.resolve()
                    break

        if resolved_transcript_path and resolved_transcript_path.is_file():
            typer.echo(f"Transcrição de fala vinculada: {resolved_transcript_path.name}")

        state = ingestion_node(
            slide_path=slide_path,
            syllabus=module,
            lesson_number=lesson,
            lesson_title=title,
            lesson_slug=resolved_slug,
            full_syllabus=structured_syllabus,
            transcript_path=resolved_transcript_path,
        )

        drafter_client = get_client(auditor=False)
        auditor_client = get_client(auditor=True)
        output = run_lesson_pipeline(
            state=state,
            client=drafter_client,
            auditor_client=auditor_client,
        )
        export_result = export_lesson_to_vault(
            vault_root=vault_root,
            output=output,
            syllabus=module,
            force=force,
        )

        typer.echo(f"Aula {lesson:02d} processada com sucesso!")
        typer.echo(f"- Wiki da Aula: {export_result.lesson_path}")
        if output.source_transcript_filename:
            typer.echo(f"- Transcrição Vinculada: {output.source_transcript_filename}")
        typer.echo(f"- Índice MOC: {export_result.index_path}")
        typer.echo(f"- Zettels exportados: {len(export_result.zettel_paths)}")
        typer.echo(f"- Relatório Factual: {export_result.audit_report_path}")
        if export_result.tension_paths:
            typer.echo(f"- Tensões Dialéticas exportadas: {len(export_result.tension_paths)}")
            if export_result.tensions_index_path:
                typer.echo(f"- Índice de Tensões: {export_result.tensions_index_path}")
    except FactCheckBlockedError as exc:
        try:
            report_path = write_blocked_audit_report(vault_root, exc.state)
        except OSError as report_error:
            typer.echo(
                f"Erro: {exc} Não foi possível salvar a auditoria pendente: {report_error}",
                err=True,
            )
            raise typer.Exit(code=1) from report_error
        typer.echo(f"Erro: {exc} Relatório pendente: {report_path}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Erro durante o processamento da aula: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def parse_tension_note(note_path: Path) -> DialecticalTension:
    """Parses an existing dialectical tension markdown file into a DialecticalTension model.

    Args:
        note_path: Path to the tension markdown note in 04_Diario_Tensoes.

    Returns:
        Populated DialecticalTension instance.

    Raises:
        None.
    """
    text = note_path.read_text(encoding="utf-8")

    slug_match = re.search(r'slug:\s*"([^"]+)"', text)
    slug = slug_match.group(1) if slug_match else note_path.stem

    title_match = re.search(r'title:\s*"([^"]+)"', text) or re.search(
        r"^#\s+(.+)$", text, re.MULTILINE
    )
    title = title_match.group(1).strip() if title_match else slug

    nature_match = re.search(
        r">\s*\[!abstract\][^\n]*\n>\s*([^\n]+)",
        text,
    )
    tension_nature = nature_match.group(1).strip() if nature_match else "Trade-off gerencial"

    disc_match = re.search(r"\|\s*\*\*Disciplina\*\*\s*\|\s*([^|]+)\|\s*([^|]+)\|", text)
    pole_a_discipline = disc_match.group(1).strip() if disc_match else "geral"
    pole_b_discipline = disc_match.group(2).strip() if disc_match else "geral"

    fw_match = re.search(r"\|\s*\*\*Modelo/Framework\*\*\s*\|\s*([^|]+)\|\s*([^|]+)\|", text)
    if not fw_match:
        pole_a_fm = re.search(r'pole_a:\s*"([^"]+)"', text)
        pole_b_fm = re.search(r'pole_b:\s*"([^"]+)"', text)
        pole_a_framework = pole_a_fm.group(1) if pole_a_fm else "Framework A"
        pole_b_framework = pole_b_fm.group(1) if pole_b_fm else "Framework B"
    else:
        pole_a_framework = fw_match.group(1).strip()
        pole_b_framework = fw_match.group(2).strip()

    thesis_match = re.search(r"\|\s*\*\*Proposição Central\*\*\s*\|\s*([^|]+)\|\s*([^|]+)\|", text)
    pole_a_thesis = thesis_match.group(1).strip() if thesis_match else "Tese A"
    pole_b_thesis = thesis_match.group(2).strip() if thesis_match else "Tese B"

    synth_match = re.search(
        r"## Diretrizes de Síntese e Arbitragem Gerencial\s*\n(.*?)(?=\n##|\Z)",
        text,
        re.DOTALL,
    )
    synthesis_guidelines = (
        synth_match.group(1).strip() if synth_match else "Síntese gerencial a definir."
    )

    z_match = re.findall(r"-\s*\[\[([^\]]+)\]\]", text)
    related_zettels = [z for z in z_match if not z.startswith("Aula_")]

    return DialecticalTension(
        slug=slug,
        title=title,
        pole_a_discipline=pole_a_discipline,
        pole_a_framework=pole_a_framework,
        pole_a_thesis=pole_a_thesis,
        pole_b_discipline=pole_b_discipline,
        pole_b_framework=pole_b_framework,
        pole_b_thesis=pole_b_thesis,
        tension_nature=tension_nature,
        synthesis_guidelines=synthesis_guidelines,
        related_zettel_slugs=related_zettels,
    )


@app.command(name="sync-tensions")
def sync_tensions(
    vault: Annotated[
        Path | None,
        typer.Option(
            "--vault",
            "-v",
            help="Caminho do Obsidian Vault (sobrescreve configuração padrão).",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Força sincronização e recupera delimitadores HTML corrompidos no índice.",
        ),
    ] = False,
) -> None:
    """Reindexa todas as notas de tensões dialéticas em 04_Diario_Tensoes/_Indice_Tensoes.md.

    Args:
        vault: Caminho opcional do Vault do Obsidian.
        force: Força a regeneração de delimitadores corrompidos.

    Returns:
        None.

    Raises:
        typer.Exit: Com código 1 em caso de erro na reindexação.
    """
    settings = get_settings()
    vault_root = vault or settings.obsidian_vault_path
    tensions_dir = vault_root / "04_Diario_Tensoes"

    if not tensions_dir.is_dir():
        typer.echo("Nenhuma nota de tensão encontrada para sincronizar.")
        return

    tension_files = [f for f in tensions_dir.glob("*.md") if f.name != "_Indice_Tensoes.md"]
    if not tension_files:
        typer.echo("Nenhuma nota de tensão encontrada para sincronizar.")
        return

    try:
        scanned_tensions: list[DialecticalTension] = []
        for file in sorted(tension_files):
            tension_model = parse_tension_note(file)
            scanned_tensions.append(tension_model)

        index_path = write_tensions_index(
            vault_root=vault_root,
            tensions=scanned_tensions,
            force=force,
        )
        typer.echo(
            f"Índice de tensões sincronizado com sucesso: {index_path} "
            f"({len(scanned_tensions)} tensões)"
        )
    except Exception as exc:
        typer.echo(f"Erro ao sincronizar índice de tensões: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _sanitize_for_terminal(text: str) -> str:
    """Normalizes diacritics into plain ASCII equivalents for robust terminal output.

    Prevents Windows console codepage mismatch and PowerShell pipe mojibake
    when stdout/stderr is captured via Tee-Object or redirection.

    Args:
        text: Input text containing potential diacritics or special characters.

    Returns:
        str: ASCII-normalized string.
    """
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _format_seconds(seconds: float) -> str:
    """Converts seconds into human-readable HH:MM:SS or MM:SS format.

    Args:
        seconds: Numeric seconds duration.

    Returns:
        str: Formatted duration string.
    """
    if seconds < 0:
        return "00s"
    total_sec = int(round(seconds))
    hours, remainder = divmod(total_sec, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}h {minutes:02d}m {secs:02d}s"
    return f"{minutes:02d}m {secs:02d}s"


@app.command(name="transcribe-batch")
def transcribe_batch(
    videos_dir: Annotated[
        Path,
        typer.Argument(
            help="Diretório contendo as videoaulas organizadas por disciplina.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
        ),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Diretório raiz para salvar as transcrições JSON (padrão: data/raw/transcripts).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    model: Annotated[
        str,
        typer.Option(
            "--model",
            "-m",
            help="Tamanho do modelo Faster-Whisper (ex.: large-v3, medium, small).",
        ),
    ] = "large-v3",
    device: Annotated[
        str | None,
        typer.Option(
            "--device",
            help="Dispositivo de computação ('cuda' ou 'cpu'). Padrão: auto-detecção.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Força reprocessamento de vídeos que já possuem transcrição válida.",
        ),
    ] = False,
) -> None:
    """Executa transcrição em lote desacoplada de videoaulas com suporte a aceleração CUDA.

    Args:
        videos_dir: Diretório raiz contendo videoaulas por disciplina.
        output_dir: Diretório de destino para transcrições em JSON.
        model: Identificador do modelo Faster-Whisper.
        device: Dispositivo de execução opcional ('cuda' ou 'cpu').
        force: Força reprocessamento de arquivos já transcritos.

    Returns:
        None.

    Raises:
        typer.Exit: Com código 1 em caso de falha crítica na inicialização.
    """
    target_output = output_dir or Path("data/raw/transcripts")
    target_output.mkdir(parents=True, exist_ok=True)

    # 1. Automatic migration of any legacy transcript folders
    migrated_count = migrate_legacy_transcripts(target_output, videos_dir=videos_dir)
    if migrated_count > 0:
        typer.echo(
            f"Migradas {migrated_count} transcricoes previas "
            "para a estrutura canonica de disciplinas."
        )

    logger = TranscriptionLogger(logs_dir=Path("logs/transcriptions"))

    try:
        typer.echo(f"Iniciando transcritor (modelo: {model}, dispositivo: {device or 'auto'})...")
        transcriber = LectureTranscriber(model_size=model, device=device)

        typer.echo(f"Processando videos em: {videos_dir}")
        typer.echo(f"Destino das transcricoes: {target_output}")
        typer.echo(f"Arquivo de log em tempo real: {logger.log_path}\n")

        start_wall_time = time.perf_counter()

        def progress_callback(event: ProgressEvent) -> None:
            now_elapsed = time.perf_counter() - start_wall_time
            video_name = _sanitize_for_terminal(event.video.video_path.name)

            if event.phase == "skipped":
                typer.echo(
                    f"[{event.index:03d}/{event.total:03d}] [SKIP] "
                    f"{event.video.discipline_slug} | {video_name} (ja transcrito)"
                )
            elif event.phase == "start":
                typer.echo(f"\n[{event.index:03d}/{event.total:03d}] Processando: {video_name}")
                module_info = (
                    f" | Modulo: {event.video.module_slug}" if event.video.module_slug else ""
                )
                safe_rel = _sanitize_for_terminal(event.video.relative_path)
                typer.echo(
                    f"            Origem: {safe_rel} "
                    f"(Disciplina: {event.video.discipline_slug}{module_info})"
                )
            elif event.phase == "extracting":
                typer.echo("            -> [1/2] Extraindo audio PCM 16kHz via FFmpeg...")
            elif event.phase == "transcribing":
                typer.echo(
                    f"            -> [2/2] FFmpeg OK ({event.extraction_seconds:.1f}s). "
                    "Transcrevendo com Faster-Whisper..."
                )
            elif event.phase == "completed":
                dur_min = event.duration_seconds / 60
                typer.echo(
                    f"            -> Concluido em {_format_seconds(event.transcription_seconds)}! "
                    f"Audio: {dur_min:.1f} min | Aceleracao: {event.speedup_factor:.1f}x"
                )

                remaining_files = event.total - event.index
                avg_time = now_elapsed / event.index if event.index > 0 else 0
                eta_seconds = avg_time * remaining_files
                pct = (event.index / event.total) * 100
                typer.echo(
                    f"            Progresso Geral: {event.index}/{event.total} ({pct:.1f}%) | "
                    f"Decorrido: {_format_seconds(now_elapsed)} | "
                    f"Estimativa restante: {_format_seconds(eta_seconds)}"
                )
            elif event.phase == "failed":
                safe_err = _sanitize_for_terminal(event.error_message or "Erro desconhecido")
                typer.secho(
                    f"            -> FALHA no arquivo: {safe_err}",
                    fg=typer.colors.RED,
                    err=True,
                )

        summary = run_transcription_batch(
            videos_dir=videos_dir,
            output_dir=target_output,
            transcriber=transcriber,
            force=force,
            progress_callback=progress_callback,
            logger=logger,
        )

        typer.echo("\n--- Lote de Transcricao Concluido com Sucesso ---")
        typer.echo(f"Total de videos encontrados: {summary.total_videos_found}")
        typer.echo(f"Videos processados nesta sessao: {summary.videos_processed}")
        typer.echo(f"Videos ignorados (ja existentes): {summary.videos_skipped}")
        typer.echo(f"Falhas: {len(summary.failed_videos)}")
        duration_hours = summary.total_duration_seconds / 3600
        typer.echo(f"Duracao de midia transcrita: {duration_hours:.2f} horas")
        typer.echo(
            f"Tempo total de processamento: {_format_seconds(summary.elapsed_processing_seconds)}"
        )
        typer.echo("\nTelemetria e relatorios persistidos:")
        typer.echo(f"- Log textual: {logger.log_path}")
        typer.echo(f"- Stream JSONL: {logger.jsonl_path}")

        if summary.failed_videos:
            typer.echo("\nVídeos que falharam durante o lote:")
            for name, err in summary.failed_videos:
                typer.echo(f"- {name}: {err}", err=True)

    except Exception as exc:
        typer.echo(f"Erro fatal na execução do lote de transcrição: {exc}", err=True)
        raise typer.Exit(code=1) from exc

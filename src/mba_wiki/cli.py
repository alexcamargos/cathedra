"""Command line interface (CLI) for the MBA Wiki Engine using Typer.

Exposes primary entrypoint commands:
- init-syllabus: Parses and persists structured syllabus from course program documents.
- build-lesson: Processes presentation slides through the full drafting, auditing,
  and humanizing pipeline, exporting markdown wiki pages and zettels to Obsidian.
"""

import re
from pathlib import Path
from typing import Annotated

import typer

from mba_wiki.agents.graph import (
    find_syllabus_module,
    ingestion_node,
    run_lesson_pipeline,
    slugify,
)
from mba_wiki.agents.llm_client import StructuredLLMClient, create_llm_client
from mba_wiki.config import get_settings
from mba_wiki.exporters.obsidian_writer import (
    export_lesson_to_vault,
    write_tensions_index,
)
from mba_wiki.ingestion.syllabus_parser import (
    load_structured_syllabus,
    process_and_save_syllabus,
)
from mba_wiki.schemas import DialecticalTension

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


def get_client() -> StructuredLLMClient:
    """Resolves and returns the active StructuredLLMClient instance.

    Args:
        None.

    Returns:
        Configured StructuredLLMClient implementation.

    Raises:
        ValueError: If client cannot be initialized or API key is missing.
    """
    if _client_override is not None:
        return _client_override
    settings = get_settings()
    return create_llm_client(
        api_key=settings.gemini_api_key,
        model=settings.llm_model_drafter,
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

        state = ingestion_node(
            slide_path=slide_path,
            syllabus=module,
            lesson_number=lesson,
            lesson_title=title,
            lesson_slug=resolved_slug,
            full_syllabus=structured_syllabus,
        )

        client = get_client()
        output = run_lesson_pipeline(state=state, client=client)
        if not output.fact_check_passed:
            typer.secho(
                "Aviso: A aula possui alertas na auditoria factual (bloqueadores não resolvidos).",
                fg=typer.colors.YELLOW,
                err=True,
            )
        export_result = export_lesson_to_vault(
            vault_root=vault_root,
            output=output,
            syllabus=module,
        )

        typer.echo(f"Aula {lesson:02d} processada com sucesso!")
        typer.echo(f"- Wiki da Aula: {export_result.lesson_path}")
        typer.echo(f"- Índice MOC: {export_result.index_path}")
        typer.echo(f"- Zettels exportados: {len(export_result.zettel_paths)}")
        typer.echo(f"- Relatório Factual: {export_result.audit_report_path}")
        if export_result.tension_paths:
            typer.echo(f"- Tensões Dialéticas exportadas: {len(export_result.tension_paths)}")
            if export_result.tensions_index_path:
                typer.echo(f"- Índice de Tensões: {export_result.tensions_index_path}")
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
) -> None:
    """Reindexa todas as notas de tensões dialéticas em 04_Diario_Tensoes/_Indice_Tensoes.md.

    Args:
        vault: Caminho opcional do Vault do Obsidian.

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

        index_path = write_tensions_index(vault_root=vault_root, tensions=scanned_tensions)
        typer.echo(
            f"Índice de tensões sincronizado com sucesso: {index_path} "
            f"({len(scanned_tensions)} tensões)"
        )
    except Exception as exc:
        typer.echo(f"Erro ao sincronizar índice de tensões: {exc}", err=True)
        raise typer.Exit(code=1) from exc

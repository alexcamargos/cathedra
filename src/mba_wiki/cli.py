"""Command line interface (CLI) for the MBA Wiki Engine using Typer.

Exposes primary entrypoint commands:
- init-syllabus: Parses and persists structured syllabus from course program documents.
- build-lesson: Processes presentation slides through the full drafting, auditing,
  and humanizing pipeline, exporting markdown wiki pages and zettels to Obsidian.
"""

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
from mba_wiki.exporters.obsidian_writer import export_lesson_to_vault
from mba_wiki.ingestion.syllabus_parser import (
    load_structured_syllabus,
    process_and_save_syllabus,
)

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
        )

        client = get_client()
        output = run_lesson_pipeline(state=state, client=client)
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
    except Exception as exc:
        typer.echo(f"Erro durante o processamento da aula: {exc}", err=True)
        raise typer.Exit(code=1) from exc

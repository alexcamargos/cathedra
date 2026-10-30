"""Unit tests for the Typer command line interface (cli.py).

Validates CLI entrypoints init-syllabus and build-lesson using CliRunner,
testing error handling for missing files, syllabus validation, and end-to-end
pipeline coordination with mock LLM client injection.
"""

from pathlib import Path
from typing import Any

import pymupdf
import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from mba_wiki.cli import app, get_client, set_client_override
from mba_wiki.schemas import (
    AtomicZettel,
    AuditClaimsResponse,
    ClaimAuditItem,
    DraftResult,
    StructuredSyllabus,
    SyllabusModule,
)
from tests.conftest import FakeLLMClient


@pytest.fixture
def cli_runner() -> CliRunner:
    """Fixture providing a Typer/Click CliRunner instance for CLI testing.

    Args:
        None.

    Returns:
        Configured CliRunner instance.

    Raises:
        None.
    """
    return CliRunner()


@pytest.fixture
def synthetic_cli_pdf(tmp_path: Path) -> Path:
    """Creates a synthetic presentation PDF with 1 slide for CLI testing.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        Path to the generated PDF file.

    Raises:
        None.
    """
    pdf_path = tmp_path / "slides_aula_01.pdf"
    doc: Any = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=720, height=405)
    page.insert_text(
        (50, 60),
        "# Critérios de Decisão de Investimento\n"
        "O método do VPL analisa os fluxos descontados à taxa de oportunidade.",
        fontsize=16,
    )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_cli_help(cli_runner: CliRunner) -> None:
    """Tests that mba-wiki displays the help message and registered commands.

    Args:
        cli_runner: CliRunner test fixture.

    Returns:
        None.

    Raises:
        None.
    """
    result = cli_runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init-syllabus" in result.stdout
    assert "build-lesson" in result.stdout


def test_init_syllabus_file_not_found(cli_runner: CliRunner) -> None:
    """Tests that init-syllabus fails gracefully when source syllabus document is missing.

    Args:
        cli_runner: CliRunner test fixture.

    Returns:
        None.

    Raises:
        None.
    """
    result = cli_runner.invoke(app, ["init-syllabus", "arquivo_inexistente.txt"])
    assert result.exit_code == 1
    assert "não encontrado" in result.stdout or "não encontrado" in result.stderr


def test_init_syllabus_success(
    tmp_path: Path,
    cli_runner: CliRunner,
    fake_llm_client: FakeLLMClient,
    mocker: MockerFixture,
) -> None:
    """Tests that init-syllabus coordinates parsing and saves ementa_estruturada.json.

    Args:
        tmp_path: Pytest temporary directory fixture.
        cli_runner: CliRunner test fixture.
        fake_llm_client: Mock LLM client fixture.
        mocker: Pytest-mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    syllabus_source = tmp_path / "ementa_bruta.txt"
    syllabus_source.write_text("Ementa de Finanças Corporativas", encoding="utf-8")
    destination_json = tmp_path / "ementa_estruturada.json"

    module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Decisões financeiras corporativas.",
        topics=["VPL", "TIR"],
        bibliography=["Livro de Finanças"],
    )
    fake_llm_client.add_structured_response(StructuredSyllabus(modules=[module]))
    mocker.patch("mba_wiki.cli.get_client", return_value=fake_llm_client)

    result = cli_runner.invoke(
        app,
        ["init-syllabus", str(syllabus_source), "--destination", str(destination_json)],
    )

    assert result.exit_code == 0
    assert "sucesso" in result.stdout.lower()
    assert destination_json.is_file()


def test_build_lesson_slide_file_not_found(cli_runner: CliRunner) -> None:
    """Tests that build-lesson aborts when slide file cannot be found.

    Args:
        cli_runner: CliRunner test fixture.

    Returns:
        None.

    Raises:
        None.
    """
    result = cli_runner.invoke(
        app,
        [
            "build-lesson",
            "slides_inexistentes.pdf",
            "--discipline",
            "financas-corporativas",
            "--lesson",
            "1",
        ],
    )
    assert result.exit_code == 1
    assert "não encontrado" in result.stdout or "não encontrado" in result.stderr


def test_build_lesson_missing_syllabus_json(
    tmp_path: Path,
    cli_runner: CliRunner,
    synthetic_cli_pdf: Path,
) -> None:
    """Tests that build-lesson aborts if ementa_estruturada.json is not present in vault.

    Args:
        tmp_path: Pytest temporary directory fixture.
        cli_runner: CliRunner test fixture.
        synthetic_cli_pdf: Synthetic PDF slide path.

    Returns:
        None.

    Raises:
        None.
    """
    vault_dir = tmp_path / "vault_mba"
    result = cli_runner.invoke(
        app,
        [
            "build-lesson",
            str(synthetic_cli_pdf),
            "--discipline",
            "financas-corporativas",
            "--lesson",
            "1",
            "--vault",
            str(vault_dir),
        ],
    )
    assert result.exit_code == 1
    output_text = (result.stdout + result.stderr).lower()
    assert "ementa estruturada não encontrada" in output_text


def test_build_lesson_discipline_not_found(
    tmp_path: Path,
    cli_runner: CliRunner,
    synthetic_cli_pdf: Path,
) -> None:
    """Tests that build-lesson aborts if the specified discipline slug is not in syllabus.

    Args:
        tmp_path: Pytest temporary directory fixture.
        cli_runner: CliRunner test fixture.
        synthetic_cli_pdf: Synthetic PDF slide path.

    Returns:
        None.

    Raises:
        None.
    """
    vault_dir = tmp_path / "vault_mba"
    syllabus_dir = vault_dir / "00_Programa_Curso"
    syllabus_dir.mkdir(parents=True, exist_ok=True)
    syllabus_json = syllabus_dir / "ementa_estruturada.json"

    module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Resumo",
        topics=["VPL"],
        bibliography=["Livro"],
    )
    syllabus_json.write_text(
        StructuredSyllabus(modules=[module]).model_dump_json(), encoding="utf-8"
    )

    result = cli_runner.invoke(
        app,
        [
            "build-lesson",
            str(synthetic_cli_pdf),
            "--discipline",
            "marketing-estrategico",
            "--lesson",
            "1",
            "--vault",
            str(vault_dir),
        ],
    )
    assert result.exit_code == 1
    output_text = (result.stdout + result.stderr).lower()
    assert "não encontrada" in output_text


def test_build_lesson_full_success(
    tmp_path: Path,
    cli_runner: CliRunner,
    synthetic_cli_pdf: Path,
    fake_llm_client: FakeLLMClient,
    mocker: MockerFixture,
) -> None:
    """Tests full successful build-lesson CLI command execution with mocked LLM pipeline.

    Args:
        tmp_path: Pytest temporary directory fixture.
        cli_runner: CliRunner test fixture.
        synthetic_cli_pdf: Synthetic PDF slide path.
        fake_llm_client: Mock LLM client fixture.
        mocker: Pytest-mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    vault_dir = tmp_path / "vault_mba"
    syllabus_dir = vault_dir / "00_Programa_Curso"
    syllabus_dir.mkdir(parents=True, exist_ok=True)
    syllabus_json = syllabus_dir / "ementa_estruturada.json"

    module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        professor="Prof. Dr. Roberto Albuquerque",
        syllabus_summary="Decisões financeiras de longo prazo.",
        topics=["Critérios de Decisão", "VPL"],
        bibliography=["Brealey, Myers & Allen."],
    )
    syllabus_json.write_text(
        StructuredSyllabus(modules=[module]).model_dump_json(), encoding="utf-8"
    )

    # 1. Drafter response
    draft_result = DraftResult(
        raw_draft="O método do VPL desconta fluxos futuros à taxa de capital da firma.",
        extracted_zettels=[
            AtomicZettel(
                slug="valor-presente-liquido",
                title="Valor Presente Líquido",
                domain_tags=["financas"],
                content_markdown="Nota conceitual de VPL.",
                related_links=[],
            )
        ],
    )
    fake_llm_client.add_structured_response(draft_result)

    # 2. Fact-Checker response
    audit_response = AuditClaimsResponse(
        claims=[
            ClaimAuditItem(
                claim_id="CLM-001",
                quote="O método do VPL desconta fluxos futuros à taxa de capital da firma.",
                category="technical",
                verdict="verified",
                severity=None,
                evidence_source="Slide 1",
            )
        ]
    )
    fake_llm_client.add_structured_response(audit_response)

    # 3. Humanizer response
    clean_prose = (
        "O método do VPL analisa fluxos de caixa futuros descontados à taxa de atratividade."
    )
    fake_llm_client.add_text_response(clean_prose)

    mocker.patch("mba_wiki.cli.get_client", return_value=fake_llm_client)

    result = cli_runner.invoke(
        app,
        [
            "build-lesson",
            str(synthetic_cli_pdf),
            "--discipline",
            "financas-corporativas",
            "--lesson",
            "1",
            "--title",
            "Critérios de Decisão",
            "--vault",
            str(vault_dir),
        ],
    )

    assert result.exit_code == 0
    assert "sucesso" in result.stdout.lower()

    # Verify generated vault structure
    wiki_lesson = (
        vault_dir
        / "01_Wiki_Disciplinas"
        / "financas-corporativas"
        / "Aula_01_criterios-de-decisao.md"
    )
    index_moc = vault_dir / "01_Wiki_Disciplinas" / "financas-corporativas" / "_Indice_Materia.md"
    zettel_file = vault_dir / "02_Zettelkasten" / "valor-presente-liquido.md"
    audit_file = vault_dir / "03_Auditoria_Factual" / "financas-corporativas_Aula_01_audit.json"

    assert wiki_lesson.is_file()
    assert index_moc.is_file()
    assert zettel_file.is_file()
    assert audit_file.is_file()


def test_get_client_override(fake_llm_client: FakeLLMClient) -> None:
    """Tests set_client_override configuring active client returned by get_client.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    set_client_override(fake_llm_client)
    try:
        assert get_client() is fake_llm_client
    finally:
        set_client_override(None)


def test_get_client_from_settings(mocker: MockerFixture) -> None:
    """Tests get_client instantiating client using application Settings when no override exists.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_client = mocker.MagicMock()
    mocker.patch("mba_wiki.cli.create_llm_client", return_value=mock_client)
    mock_settings = mocker.MagicMock()
    mock_settings.gemini_api_key = "fake_key"
    mock_settings.llm_model_drafter = "gemini-2.5-pro"
    mocker.patch("mba_wiki.cli.get_settings", return_value=mock_settings)

    client = get_client()
    assert client is mock_client


def test_build_lesson_exports_dialectical_tensions(
    cli_runner: CliRunner,
    synthetic_cli_pdf: Path,
    fake_llm_client: FakeLLMClient,
    tmp_path: Path,
) -> None:
    """Tests that build-lesson generates dialectical tension notes and updates tensions index.

    Args:
        cli_runner: Typer CLI runner fixture.
        synthetic_cli_pdf: Synthetic PDF slide fixture.
        fake_llm_client: Mock LLM client fixture.
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from mba_wiki.schemas import DialecticalTension

    vault_dir = tmp_path / "vault_tensions"
    vault_dir.mkdir(parents=True, exist_ok=True)
    syllabus_dir = vault_dir / "00_Programa_Curso"
    syllabus_dir.mkdir(parents=True, exist_ok=True)
    syllabus_file = syllabus_dir / "ementa_estruturada.json"

    module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Finanças corporativas e decisões.",
        topics=["VPL", "Custos"],
        bibliography=["Brealey"],
    )
    syllabus = StructuredSyllabus(modules=[module])
    syllabus_file.write_text(syllabus.model_dump_json(indent=2), encoding="utf-8")

    tension = DialecticalTension(
        slug="eficiencia-vs-resiliencia",
        title="Eficiência vs Resiliência",
        pole_a_discipline="financas-corporativas",
        pole_a_framework="Otimização de Custos",
        pole_a_thesis="Minimizar despesas operacionais.",
        pole_b_discipline="gestao-estrategica",
        pole_b_framework="Capacidades Dinâmicas",
        pole_b_thesis="Investir em redundâncias estratégicas.",
        tension_nature="Curto vs Longo Prazo",
        synthesis_guidelines="Criar reservas estratégicas condicionais.",
    )

    draft_result = DraftResult(
        raw_draft="Rascunho de finanças corporativas integrando tensões de longo prazo.",
        detected_tensions=[tension],
    )
    fake_llm_client.add_structured_response(draft_result)
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))
    fake_llm_client.add_text_response("Rascunho polido de finanças corporativas.")
    set_client_override(fake_llm_client)

    try:
        result = cli_runner.invoke(
            app,
            [
                "build-lesson",
                str(synthetic_cli_pdf),
                "--discipline",
                "financas-corporativas",
                "--lesson",
                "1",
                "--vault",
                str(vault_dir),
            ],
        )
        assert result.exit_code == 0
        assert "Tensões Dialéticas exportadas: 1" in result.output

        tension_file = vault_dir / "04_Diario_Tensoes" / "eficiencia-vs-resiliencia.md"
        assert tension_file.is_file()
        index_file = vault_dir / "04_Diario_Tensoes" / "_Indice_Tensoes.md"
        assert index_file.is_file()
        assert "Eficiência vs Resiliência" in index_file.read_text(encoding="utf-8")
    finally:
        set_client_override(None)


def test_sync_tensions_command(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """Tests sync-tensions command re-indexing existing notes into _Indice_Tensoes.md.

    Args:
        cli_runner: Typer CLI runner fixture.
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    vault_dir = tmp_path / "vault_sync"
    tensions_dir = vault_dir / "04_Diario_Tensoes"
    tensions_dir.mkdir(parents=True, exist_ok=True)

    # Note 1
    note1 = (
        "---\n"
        'type: "diario_tensao"\n'
        'slug: "custo-vs-qualidade"\n'
        'title: "Custo vs Qualidade"\n'
        'pole_a: "Lean Operations"\n'
        'pole_b: "Six Sigma"\n'
        "---\n\n"
        "# Custo vs Qualidade\n\n"
        "> [!abstract] Natureza do Trade-off\n"
        "> Eficiência em Custo vs Excelência em Qualidade\n\n"
        "| Dimensão | Polo A (Tese) | Polo B (Antítese) |\n"
        "| :--- | :--- | :--- |\n"
        "| **Disciplina** | operacoes | qualidade |\n"
        "| **Modelo/Framework** | Lean | Six Sigma |\n"
        "| **Proposição Central** | Eliminar desperdícios | Zero defeitos |\n"
    )
    (tensions_dir / "custo-vs-qualidade.md").write_text(note1, encoding="utf-8")

    result = cli_runner.invoke(
        app,
        ["sync-tensions", "--vault", str(vault_dir)],
    )
    assert result.exit_code == 0
    assert "Índice de tensões sincronizado" in result.output

    index_file = tensions_dir / "_Indice_Tensoes.md"
    assert index_file.is_file()
    assert "- [[custo-vs-qualidade|Custo vs Qualidade]]" in index_file.read_text(encoding="utf-8")


def test_sync_tensions_empty_vault(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """Tests sync-tensions gracefully reporting when no tension notes exist.

    Args:
        cli_runner: Typer CLI runner fixture.
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    vault_dir = tmp_path / "vault_empty"
    result = cli_runner.invoke(
        app,
        ["sync-tensions", "--vault", str(vault_dir)],
    )
    assert result.exit_code == 0
    assert "Nenhuma nota de tensão encontrada" in result.output

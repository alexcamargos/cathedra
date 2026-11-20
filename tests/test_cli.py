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
    LessonAuditReport,
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
        "O método do VPL analisa os fluxos descontados à taxa de oportunidade.\n"
        "O VPL desconta fluxos futuros.",
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
                evidence_kind="slide",
                evidence_locator=1,
                evidence_quote="O VPL desconta fluxos futuros.",
            )
        ]
    )
    fake_llm_client.add_structured_response(audit_response)

    # 3. Humanizer response
    clean_prose = (
        "O método do VPL analisa fluxos de caixa futuros descontados à taxa de atratividade."
    )
    fake_llm_client.add_text_response(clean_prose)
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))

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


def test_build_lesson_saves_blocked_audit_without_changing_published_files(
    tmp_path: Path,
    cli_runner: CliRunner,
    synthetic_cli_pdf: Path,
    fake_llm_client: FakeLLMClient,
    mocker: MockerFixture,
) -> None:
    """A blocked lesson reports the verdict and leaves prior published files intact."""
    vault = tmp_path / "vault"
    syllabus_dir = vault / "00_Programa_Curso"
    syllabus_dir.mkdir(parents=True)
    module = SyllabusModule(
        discipline_slug="financas",
        discipline_name="Finanças",
        syllabus_summary="Finanças",
        topics=[],
        bibliography=[],
    )
    (syllabus_dir / "ementa_estruturada.json").write_text(
        StructuredSyllabus(modules=[module]).model_dump_json(), encoding="utf-8"
    )
    published = vault / "01_Wiki_Disciplinas" / "financas" / "Aula_01_vpl.md"
    published.parent.mkdir(parents=True)
    published.write_text("Minha aula anterior", encoding="utf-8")
    approved_audit = vault / "03_Auditoria_Factual" / "financas_Aula_01_audit.json"
    approved_audit.parent.mkdir(parents=True)
    approved_audit.write_text("auditoria anterior", encoding="utf-8")
    fake_llm_client.add_structured_response(
        DraftResult(raw_draft="Afirmação falsa.", extracted_zettels=[])
    )
    fake_llm_client.add_structured_response(
        AuditClaimsResponse(
            claims=[
                ClaimAuditItem(
                    claim_id="C1",
                    quote="Afirmação falsa.",
                    category="technical",
                    verdict="false",
                    severity="S1",
                )
            ]
        )
    )
    mocker.patch("mba_wiki.cli.get_client", return_value=fake_llm_client)

    result = cli_runner.invoke(
        app,
        [
            "build-lesson",
            str(synthetic_cli_pdf),
            "--discipline",
            "financas",
            "--lesson",
            "1",
            "--title",
            "VPL",
            "--vault",
            str(vault),
            "--force",
        ],
    )

    assert result.exit_code != 0
    assert "auditoria factual" in result.output.lower()
    assert published.read_text(encoding="utf-8") == "Minha aula anterior"
    assert approved_audit.read_text(encoding="utf-8") == "auditoria anterior"
    assert not (vault / "02_Zettelkasten").exists()
    assert not (vault / "04_Diario_Tensoes").exists()
    pending = vault / "03_Auditoria_Factual" / "pendentes" / "financas_Aula_01_audit.json"
    report = LessonAuditReport.model_validate_json(pending.read_text(encoding="utf-8"))
    assert report.fact_check_passed is False
    assert report.audit_items[0].claim_id == "C1"
    assert [call.call_type for call in fake_llm_client.calls] == ["structured", "structured"]


def test_build_lesson_saves_final_audit_blocker(
    tmp_path: Path,
    cli_runner: CliRunner,
    synthetic_cli_pdf: Path,
    fake_llm_client: FakeLLMClient,
    mocker: MockerFixture,
) -> None:
    """The CLI retains final-audit findings and does not publish a rewritten error."""
    vault = tmp_path / "vault"
    syllabus_dir = vault / "00_Programa_Curso"
    syllabus_dir.mkdir(parents=True)
    module = SyllabusModule(
        discipline_slug="financas",
        discipline_name="Finanças",
        syllabus_summary="Finanças",
        topics=[],
        bibliography=[],
    )
    (syllabus_dir / "ementa_estruturada.json").write_text(
        StructuredSyllabus(modules=[module]).model_dump_json(), encoding="utf-8"
    )
    fake_llm_client.add_structured_response(DraftResult(raw_draft="A taxa é 10%."))
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))
    fake_llm_client.add_text_response("A taxa é 20%.")
    fake_llm_client.add_structured_response(
        AuditClaimsResponse(
            claims=[
                ClaimAuditItem(
                    claim_id="C1",
                    quote="A taxa é 20%.",
                    category="metric",
                    verdict="unsupported",
                    severity="S4",
                )
            ]
        )
    )
    mocker.patch("mba_wiki.cli.get_client", return_value=fake_llm_client)

    result = cli_runner.invoke(
        app,
        [
            "build-lesson",
            str(synthetic_cli_pdf),
            "--discipline",
            "financas",
            "--lesson",
            "1",
            "--vault",
            str(vault),
        ],
    )

    assert result.exit_code != 0
    assert not (vault / "01_Wiki_Disciplinas").exists()
    pending = vault / "03_Auditoria_Factual" / "pendentes" / "financas_Aula_01_audit.json"
    report = LessonAuditReport.model_validate_json(pending.read_text(encoding="utf-8"))
    assert not report.fact_check_passed
    assert report.audit_items[0].audit_stage == "final"
    assert report.audit_items[0].quote == "A taxa é 20%."


def test_build_lesson_rejects_verified_claim_without_located_evidence(
    tmp_path: Path,
    cli_runner: CliRunner,
    synthetic_cli_pdf: Path,
    fake_llm_client: FakeLLMClient,
    mocker: MockerFixture,
) -> None:
    """An ungrounded verified verdict stays pending and cannot publish a lesson."""
    vault = tmp_path / "vault"
    syllabus_dir = vault / "00_Programa_Curso"
    syllabus_dir.mkdir(parents=True)
    module = SyllabusModule(
        discipline_slug="financas",
        discipline_name="Finanças",
        syllabus_summary="Finanças",
        topics=[],
        bibliography=["Livro de Finanças"],
    )
    (syllabus_dir / "ementa_estruturada.json").write_text(
        StructuredSyllabus(modules=[module]).model_dump_json(), encoding="utf-8"
    )
    fake_llm_client.add_structured_response(DraftResult(raw_draft="A taxa é 20%."))
    fake_llm_client.add_structured_response(
        AuditClaimsResponse(
            claims=[
                ClaimAuditItem(
                    claim_id="C1",
                    quote="A taxa é 20%.",
                    category="metric",
                    verdict="verified",
                    evidence_source="Livro de Finanças",
                )
            ]
        )
    )
    mocker.patch("mba_wiki.cli.get_client", return_value=fake_llm_client)

    result = cli_runner.invoke(
        app,
        [
            "build-lesson",
            str(synthetic_cli_pdf),
            "--discipline",
            "financas",
            "--lesson",
            "1",
            "--vault",
            str(vault),
        ],
    )

    assert result.exit_code != 0
    assert not (vault / "01_Wiki_Disciplinas").exists()
    pending = vault / "03_Auditoria_Factual" / "pendentes" / "financas_Aula_01_audit.json"
    report = LessonAuditReport.model_validate_json(pending.read_text(encoding="utf-8"))
    assert report.audit_items[0].evidence_status == "pending_review"
    assert report.audit_items[0].evidence_source is None


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
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))
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


def test_get_client_model_routing_drafter_and_auditor(mocker: MockerFixture) -> None:
    """Tests that get_client routes to the specialized model for drafter and auditor.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_create = mocker.patch("mba_wiki.cli.create_llm_client")
    mock_settings = mocker.patch("mba_wiki.cli.get_settings")
    mock_settings.return_value.gemini_api_key = "dummy-key"
    mock_settings.return_value.llm_backend = "gemini_rest"
    mock_settings.return_value.llm_model_drafter = "gemini-2.5-flash"
    mock_settings.return_value.llm_model_auditor = "gemini-2.5-pro"

    # Reset override to ensure get_client reads settings
    set_client_override(None)

    # 1. Drafter routing
    get_client(auditor=False)
    mock_create.assert_called_with(
        api_key="dummy-key",
        model="gemini-2.5-flash",
        backend="gemini_rest",
    )

    # 2. Auditor routing
    get_client(auditor=True)
    mock_create.assert_called_with(
        api_key="dummy-key",
        model="gemini-2.5-pro",
        backend="gemini_rest",
    )


def test_build_lesson_with_force_recovers_corrupted_vault(
    cli_runner: CliRunner,
    synthetic_cli_pdf: Path,
    tmp_path: Path,
    fake_llm_client: FakeLLMClient,
) -> None:
    """Tests build-lesson with --force recovers corrupted delimiters instead of crashing.

    Args:
        cli_runner: CliRunner test fixture.
        synthetic_cli_pdf: Synthetic PDF slide file fixture.
        tmp_path: Pytest temporary directory fixture.
        fake_llm_client: Fake LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    vault_dir = tmp_path / "vault_force"
    vault_dir.mkdir(parents=True, exist_ok=True)
    prog_dir = vault_dir / "00_Programa_Curso"
    prog_dir.mkdir(parents=True, exist_ok=True)
    syllabus_file = prog_dir / "ementa_estruturada.json"

    module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Análise de decisões de investimento.",
        topics=["VPL"],
        bibliography=["Livro"],
    )
    syllabus = StructuredSyllabus(
        course_title="MBA Executivo",
        institution="FGV",
        modules=[module],
    )
    syllabus_file.write_text(syllabus.model_dump_json(indent=2), encoding="utf-8")

    # Create an existing lesson file with corrupted delimiters
    disc_dir = vault_dir / "01_Wiki_Disciplinas" / "financas-corporativas"
    disc_dir.mkdir(parents=True, exist_ok=True)
    corrupted_lesson = disc_dir / "Aula_01_criterios-decisao.md"
    corrupted_lesson.write_text(
        "# Aula 01\nTexto antigo.\n## Notas Pessoais de Aula\nMinha nota importante.",
        encoding="utf-8",
    )

    fake_llm_client.add_structured_response(
        DraftResult(
            lesson_title="Critérios de Decisão de Investimento",
            lesson_slug="criterios-decisao",
            theme_intro="Introdução teórica ao VPL.",
            expanded_sections=["O método do VPL analisa fluxos descontados."],
            raw_draft="O método do VPL analisa fluxos descontados.",
            extracted_zettels=[],
            cross_links=[],
        )
    )
    fake_llm_client.add_structured_response(
        AuditClaimsResponse(claims=[], overall_verdict="approved")
    )
    fake_llm_client.add_text_response("Texto humanizado sobre o VPL.")
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))

    set_client_override(fake_llm_client)
    try:
        # Run with --force / -f
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
                "Critérios de Decisão de Investimento",
                "--slug",
                "criterios-decisao",
                "--vault",
                str(vault_dir),
                "--force",
            ],
        )
        assert result.exit_code == 0
        assert "Aula 01 processada com sucesso" in result.stdout
        content = corrupted_lesson.read_text(encoding="utf-8")
        assert "<!-- AUTO-CONTENT:START -->" in content
        assert "Texto antigo." in content
        assert "Minha nota importante." in content
    finally:
        set_client_override(None)


def test_transcribe_batch_help(cli_runner: CliRunner) -> None:
    """Tests that transcribe-batch command displays its options and description.

    Args:
        cli_runner: CliRunner fixture.

    Returns:
        None.

    Raises:
        None.
    """
    result = cli_runner.invoke(app, ["transcribe-batch", "--help"])
    assert result.exit_code == 0
    assert "transcribe-batch" in result.stdout
    assert "--model" in result.stdout
    assert "--output-dir" in result.stdout
    assert "--force" in result.stdout


def test_transcribe_batch_missing_dir(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Tests failure when videos directory does not exist.

    Args:
        cli_runner: CliRunner fixture.
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    non_existent = tmp_path / "pastas_inexistente"
    result = cli_runner.invoke(app, ["transcribe-batch", str(non_existent)])
    assert result.exit_code != 0


def test_transcribe_batch_success(
    cli_runner: CliRunner, tmp_path: Path, mocker: MockerFixture
) -> None:
    """Tests successful invocation of transcribe-batch with summary report output.

    Args:
        cli_runner: CliRunner fixture.
        tmp_path: Pytest temporary directory fixture.
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from mba_wiki.transcription.batch_runner import BatchRunSummary

    mock_summary = BatchRunSummary(
        total_videos_found=5,
        videos_processed=4,
        videos_skipped=1,
        failed_videos=[],
        total_duration_seconds=36000.0,
        elapsed_processing_seconds=450.0,
    )

    mocker.patch(
        "mba_wiki.cli.LectureTranscriber",
        return_value=mocker.MagicMock(),
    )
    mock_run = mocker.patch(
        "mba_wiki.cli.run_transcription_batch",
        return_value=mock_summary,
    )

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()

    result = cli_runner.invoke(app, ["transcribe-batch", str(videos_dir)])
    assert result.exit_code == 0
    assert "Lote de Transcricao Concluido com Sucesso" in result.stdout
    assert "Total de videos encontrados: 5" in result.stdout
    assert "Videos processados nesta sessao: 4" in result.stdout
    assert "Videos ignorados (ja existentes): 1" in result.stdout
    mock_run.assert_called_once()


def test_transcribe_batch_with_options(
    cli_runner: CliRunner, tmp_path: Path, mocker: MockerFixture
) -> None:
    """Tests transcribe-batch forwarding custom CLI options to transcriber and runner.

    Args:
        cli_runner: CliRunner fixture.
        tmp_path: Pytest temporary directory fixture.
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from mba_wiki.transcription.batch_runner import BatchRunSummary

    mock_summary = BatchRunSummary(
        total_videos_found=1,
        videos_processed=1,
        videos_skipped=0,
        failed_videos=[],
        total_duration_seconds=7200.0,
        elapsed_processing_seconds=120.0,
    )

    mock_transcriber_cls = mocker.patch(
        "mba_wiki.cli.LectureTranscriber",
        return_value=mocker.MagicMock(),
    )
    mock_run = mocker.patch(
        "mba_wiki.cli.run_transcription_batch",
        return_value=mock_summary,
    )

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    custom_out = tmp_path / "custom_out"

    result = cli_runner.invoke(
        app,
        [
            "transcribe-batch",
            str(videos_dir),
            "--output-dir",
            str(custom_out),
            "--model",
            "medium",
            "--device",
            "cpu",
            "--force",
        ],
    )
    assert result.exit_code == 0
    mock_transcriber_cls.assert_called_once_with(model_size="medium", device="cpu")
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["force"] is True


def test_transcribe_batch_rejects_collision_before_initializing_model(
    cli_runner: CliRunner,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    videos = tmp_path / "videos" / "marketing"
    videos.mkdir(parents=True)
    (videos / "aula.mp4").write_bytes(b"video 1")
    (videos / "aula.mkv").write_bytes(b"video 2")
    output = tmp_path / "output"
    transcriber = mocker.patch("mba_wiki.cli.LectureTranscriber")
    result = cli_runner.invoke(
        app, ["transcribe-batch", str(videos.parent), "--output-dir", str(output), "--force"]
    )
    assert result.exit_code != 0
    assert "colis" in result.output.lower()
    transcriber.assert_not_called()
    assert not output.exists()


def test_transcribe_batch_reports_unverified_files_as_pending(
    cli_runner: CliRunner,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    from mba_wiki.transcription.batch_runner import BatchRunSummary

    videos = tmp_path / "videos"
    videos.mkdir()
    mocker.patch("mba_wiki.cli.LectureTranscriber", return_value=mocker.MagicMock())
    mocker.patch(
        "mba_wiki.cli.run_transcription_batch",
        return_value=BatchRunSummary(total_videos_found=1, videos_unverified=1),
    )
    result = cli_runner.invoke(app, ["transcribe-batch", str(videos)])
    assert result.exit_code != 0
    assert "Transcricoes anteriores nao verificadas: 1" in result.output
    assert "Pendencias" in result.output


def test_transcribe_batch_reports_previous_copy_path(
    cli_runner: CliRunner,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    from mba_wiki.transcription.batch_runner import BatchRunSummary, DiscoveredVideo, ProgressEvent

    videos = tmp_path / "videos"
    videos.mkdir()
    backup = tmp_path / "transcripts" / ".history" / "financas" / "aula.backup.json"
    mocker.patch("mba_wiki.cli.LectureTranscriber", return_value=mocker.MagicMock())

    def run_fake(**kwargs: Any) -> BatchRunSummary:
        callback = kwargs["progress_callback"]
        callback(
            ProgressEvent(
                index=1,
                total=1,
                video=DiscoveredVideo(video_path=videos / "aula.mp4", discipline_slug="financas"),
                phase="completed",
                backup_path=backup,
            )
        )
        return BatchRunSummary(total_videos_found=1, videos_processed=1)

    mocker.patch("mba_wiki.cli.run_transcription_batch", side_effect=run_fake)
    result = cli_runner.invoke(app, ["transcribe-batch", str(videos)])
    assert result.exit_code == 0
    assert "Copia anterior:" in result.output
    assert str(backup) in result.output


def test_build_lesson_with_explicit_transcript(
    cli_runner: CliRunner,
    synthetic_cli_pdf: Path,
    tmp_path: Path,
    fake_llm_client: FakeLLMClient,
) -> None:
    """Tests build-lesson execution when explicit transcript JSON option is provided.

    Args:
        cli_runner: CliRunner fixture.
        synthetic_cli_pdf: PDF slides fixture.
        tmp_path: Temporary directory fixture.
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from datetime import UTC, datetime

    from mba_wiki.schemas import VideoTranscript

    vault_dir = tmp_path / "vault"
    prog_dir = vault_dir / "00_Programa_Curso"
    prog_dir.mkdir(parents=True)

    syllabus = StructuredSyllabus(
        modules=[
            SyllabusModule(
                discipline_slug="financas-corporativas",
                discipline_name="Finanças Corporativas",
                syllabus_summary="Critérios de avaliação de investimentos.",
                topics=["VPL", "TIR"],
                bibliography=["Brealey, Myers."],
            )
        ]
    )
    (prog_dir / "ementa_estruturada.json").write_text(
        syllabus.model_dump_json(indent=2), encoding="utf-8"
    )

    transcript = VideoTranscript(
        source_filename="aula_01_financas.mp4",
        discipline_slug="financas-corporativas",
        duration_seconds=3600.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime.now(UTC),
        full_text_raw="Texto gravado da aula",
        full_text_cleaned="O professor detalhou o VPL com exemplos práticos.",
        segments=[],
    )
    transcript_file = tmp_path / "aula_01_financas.json"
    transcript_file.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")

    fake_llm_client.add_structured_response(
        DraftResult(
            raw_draft="O método do VPL analisa os fluxos descontados à taxa de oportunidade.",
            extracted_zettels=[],
            cross_links=[],
            detected_tensions=[],
        )
    )
    fake_llm_client.add_structured_response(
        AuditClaimsResponse(claims=[], overall_verdict="approved")
    )
    fake_llm_client.add_text_response("Texto humanizado sobre o VPL.")
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))

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
                "--transcript",
                str(transcript_file),
            ],
        )
        assert result.exit_code == 0
        assert "Transcrição de fala vinculada" in result.stdout
        assert "Aula 01 processada com sucesso" in result.stdout
        assert "Transcrição Vinculada: aula_01_financas.mp4" in result.stdout
    finally:
        set_client_override(None)


def test_bind_transcripts_cli_dry_run_and_apply(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """Tests bind-transcripts CLI in dry-run mode and real update mode."""
    from datetime import UTC, datetime

    from mba_wiki.schemas import VideoTranscript

    vault_dir = tmp_path / "vault"
    prog_dir = vault_dir / "00_Programa_Curso"
    prog_dir.mkdir(parents=True)
    syllabus = StructuredSyllabus(
        modules=[
            SyllabusModule(
                discipline_slug="fundamentos-de-estatistica",
                discipline_name="Fundamentos de Estatística",
                syllabus_summary="Base estatística.",
                topics=["Probabilidade"],
                bibliography=["Favero"],
            )
        ]
    )
    (prog_dir / "ementa_estruturada.json").write_text(
        syllabus.model_dump_json(indent=2), encoding="utf-8"
    )

    transcripts_dir = tmp_path / "transcripts"
    disc_dir = transcripts_dir / "fundamentos-de-estatistica"
    disc_dir.mkdir(parents=True)
    json_path = disc_dir / "01-Fundamentos-de-Estatistica-I.json"
    transcript = VideoTranscript(
        source_filename="01-Fundamentos-de-Estatistica-I.mp4",
        discipline_slug="módulo-01-fundamentos",
        lesson_number=None,
        duration_seconds=120.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime(2026, 11, 9, 2, 0, tzinfo=UTC),
        full_text_raw="texto",
        full_text_cleaned="texto",
        segments=[],
    )
    json_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")

    dry_res = cli_runner.invoke(
        app,
        [
            "bind-transcripts",
            "--vault",
            str(vault_dir),
            "--transcripts-dir",
            str(transcripts_dir),
            "--dry-run",
        ],
    )
    assert dry_res.exit_code == 0, dry_res.output
    assert "Simulação (dry-run)" in dry_res.output
    assert "Atualizados (previstos): 1" in dry_res.output
    before = VideoTranscript.model_validate_json(json_path.read_text(encoding="utf-8"))
    assert before.lesson_number is None

    apply_res = cli_runner.invoke(
        app,
        [
            "bind-transcripts",
            "--vault",
            str(vault_dir),
            "--transcripts-dir",
            str(transcripts_dir),
        ],
    )
    assert apply_res.exit_code == 0, apply_res.output
    assert "Vinculação concluída" in apply_res.output
    assert "Atualizados: 1" in apply_res.output
    after = VideoTranscript.model_validate_json(json_path.read_text(encoding="utf-8"))
    assert after.discipline_slug == "fundamentos-de-estatistica"
    assert after.lesson_number == 1


def test_bind_transcripts_cli_missing_syllabus_exits_with_error(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """Fails cleanly when ementa_estruturada.json does not exist."""
    res = cli_runner.invoke(
        app,
        [
            "bind-transcripts",
            "--vault",
            str(tmp_path / "empty_vault"),
            "--transcripts-dir",
            str(tmp_path),
        ],
    )
    assert res.exit_code == 1
    assert "Ementa estruturada não encontrada" in res.output

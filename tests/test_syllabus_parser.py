"""Unit tests for the course syllabus ingestion parser module.

Validates reading syllabus source files, dynamically loading system prompts,
structuring modules via StructuredLLMClient, and persisting ementa_estruturada.json.
"""

from pathlib import Path
from typing import Any

import pymupdf
import pytest
from pydantic import ValidationError

from mba_wiki.ingestion.syllabus_parser import (
    get_syllabus_parser_prompt,
    load_structured_syllabus,
    parse_syllabus,
    process_and_save_syllabus,
    read_syllabus_source,
    save_structured_syllabus,
)
from mba_wiki.schemas import StructuredSyllabus, SyllabusModule
from tests.conftest import FakeLLMClient


def test_get_syllabus_parser_prompt_loads_from_markdown() -> None:
    """Tests that syllabus parser prompt is dynamically loaded from markdown file.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    prompt = get_syllabus_parser_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 50
    assert "discipline_slug" in prompt
    assert "syllabus_summary" in prompt


def test_read_syllabus_source_txt(sample_syllabus_path: Path) -> None:
    """Tests reading syllabus content from a plain text file.

    Args:
        sample_syllabus_path: Fixture path pointing to sample_syllabus.txt.

    Returns:
        None.

    Raises:
        None.
    """
    content = read_syllabus_source(sample_syllabus_path)
    assert "Finanças Corporativas e Análise de Valor" in content
    assert "financas-corporativas" in content
    assert "EMENTA E OBJETIVOS" in content


def test_read_syllabus_source_missing_file_raises(tmp_path: Path) -> None:
    """Tests that reading a non-existent file path raises FileNotFoundError.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        None.

    Raises:
        None.
    """
    missing_file = tmp_path / "non_existent_syllabus.txt"
    with pytest.raises(FileNotFoundError, match="Syllabus source file not found"):
        read_syllabus_source(missing_file)


def test_parse_syllabus_with_fake_llm(
    fake_llm_client: FakeLLMClient,
    sample_syllabus_text: str,
) -> None:
    """Tests syllabus parsing into StructuredSyllabus using FakeLLMClient.

    Args:
        fake_llm_client: Mock LLM client fixture.
        sample_syllabus_text: Raw text fixture of sample syllabus.

    Returns:
        None.

    Raises:
        None.
    """
    expected_module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas e Análise de Valor",
        professor="Prof. Dr. Roberto Albuquerque",
        syllabus_summary="Aborda decisões financeiras corporativas e valuation.",
        topics=["VPL", "WACC", "Estrutura de Capital"],
        bibliography=["Brealey, Myers. Princípios de Finanças Corporativas."],
    )
    canned_syllabus = StructuredSyllabus(modules=[expected_module])
    fake_llm_client.add_structured_response(canned_syllabus)

    result = parse_syllabus(source_text=sample_syllabus_text, client=fake_llm_client)

    assert isinstance(result, StructuredSyllabus)
    assert len(result.modules) == 1
    assert result.modules[0].discipline_slug == "financas-corporativas"
    assert result.modules[0].discipline_name == "Finanças Corporativas e Análise de Valor"
    assert result.modules[0].professor == "Prof. Dr. Roberto Albuquerque"

    # Verify client invocation parameters
    assert fake_llm_client.last_call is not None
    assert fake_llm_client.last_call.call_type == "structured"
    assert fake_llm_client.last_call.response_model is StructuredSyllabus
    assert "discipline_slug" in fake_llm_client.last_call.system_prompt
    assert sample_syllabus_text == fake_llm_client.last_call.user_prompt


def test_save_and_load_structured_syllabus(tmp_path: Path) -> None:
    """Tests serializing StructuredSyllabus to JSON and loading it back idempotently.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        None.

    Raises:
        None.
    """
    module = SyllabusModule(
        discipline_slug="lideranca-estrategica",
        discipline_name="Liderança Estratégica e Cultura",
        professor="Dra. Helena Mendes",
        syllabus_summary="Desenvolvimento de competências de liderança e gestão de equipes.",
        topics=["Comportamento Organizacional", "Gestão de Mudança", "Tomada de Decisão"],
        bibliography=["Drucker, Peter. O Gestor Eficaz."],
    )
    syllabus = StructuredSyllabus(modules=[module])
    dest_path = tmp_path / "subfolder" / "ementa_estruturada.json"

    saved_path = save_structured_syllabus(syllabus=syllabus, destination_path=dest_path)
    assert saved_path == dest_path
    assert dest_path.is_file()

    loaded = load_structured_syllabus(dest_path)
    assert loaded == syllabus
    assert len(loaded.modules) == 1
    assert loaded.modules[0].discipline_slug == "lideranca-estrategica"


def test_load_structured_syllabus_invalid_json_raises(tmp_path: Path) -> None:
    """Tests that loading corrupted JSON raises ValidationError or ValueError.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        None.

    Raises:
        None.
    """
    corrupt_file = tmp_path / "corrupt_ementa.json"
    corrupt_file.write_text('{"modules": [{"discipline_slug": 123}]}', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_structured_syllabus(corrupt_file)


def test_load_structured_syllabus_missing_file_raises(tmp_path: Path) -> None:
    """Tests that loading a non-existent JSON file raises FileNotFoundError.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        None.

    Raises:
        None.
    """
    missing_file = tmp_path / "non_existent.json"
    with pytest.raises(FileNotFoundError, match="Structured syllabus file not found"):
        load_structured_syllabus(missing_file)


def test_process_and_save_syllabus_end_to_end(
    tmp_path: Path,
    fake_llm_client: FakeLLMClient,
    sample_syllabus_path: Path,
) -> None:
    """Tests end-to-end workflow: reading file, LLM structuring, and disk persistence.

    Args:
        tmp_path: Temporary directory provided by pytest.
        fake_llm_client: Mock LLM client fixture.
        sample_syllabus_path: Path to sample syllabus text file fixture.

    Returns:
        None.

    Raises:
        None.
    """
    module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas e Análise de Valor",
        professor="Prof. Dr. Roberto Albuquerque",
        syllabus_summary="Decisões de investimento e financiamento empresarial.",
        topics=["VPL", "WACC", "Valuation"],
        bibliography=["Brealey, Myers. Princípios de Finanças Corporativas."],
    )
    fake_llm_client.add_structured_response(StructuredSyllabus(modules=[module]))

    destination = tmp_path / "vault" / "00_Programa_Curso" / "ementa_estruturada.json"
    result = process_and_save_syllabus(
        source_path=sample_syllabus_path,
        destination_path=destination,
        client=fake_llm_client,
    )

    assert result.modules[0].discipline_slug == "financas-corporativas"
    assert destination.is_file()

    # Verify persisted content on disk can be loaded
    persisted = load_structured_syllabus(destination)
    assert persisted == result


def test_get_syllabus_parser_prompt_missing_file_raises(tmp_path: Path) -> None:
    """Tests that get_syllabus_parser_prompt raises FileNotFoundError when path is missing.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    missing_path = tmp_path / "missing_prompt.md"
    with pytest.raises(FileNotFoundError, match="Syllabus parser prompt file not found"):
        get_syllabus_parser_prompt(missing_path)


def test_read_syllabus_source_pdf(tmp_path: Path) -> None:
    """Tests extracting syllabus markdown content from a PDF file using pymupdf4llm.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    pdf_path = tmp_path / "programa_curso.pdf"
    doc: Any = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=720, height=405)
    page.insert_text(
        (50, 60),
        "# Programa de Curso: MBA em Finanças\n"
        "Disciplina: Finanças Corporativas\n"
        "Ementa sobre avaliação de projetos e valuation.",
        fontsize=16,
    )
    doc.save(str(pdf_path))
    doc.close()

    content = read_syllabus_source(pdf_path)
    assert "MBA em Finanças" in content or "Finanças Corporativas" in content

"""Unit tests for the slide ingestion parser module (slide_parser.py).

Validates extracting text slide by slide, preserving Markdown tables, and isolating
LaTeX equations into SlideChunk Pydantic models from synthetic PDF and PPTX files.
"""

from pathlib import Path
from typing import Any

import pptx
import pymupdf
import pytest

from cathedra.ingestion.slide_parser import (
    extract_latex_equations,
    infer_slide_title,
    parse_pdf_slides,
    parse_pptx_slides,
    parse_slides,
    table_to_markdown,
)
from cathedra.schemas import SlideChunk


@pytest.fixture
def synthetic_pdf_path(tmp_path: Path) -> Path:
    """Creates a minimal synthetic PDF file with 2 slides containing text and LaTeX.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        Path to the generated PDF file.

    Raises:
        None.
    """
    pdf_path = tmp_path / "test_presentation.pdf"
    doc: Any = pymupdf.open()  # type: ignore[no-untyped-call]

    # Slide 1: Introduction
    page1 = doc.new_page(width=720, height=405)
    page1.insert_text(
        (50, 60),
        "# Introdução a Finanças Corporativas\n"
        "Prof. Dr. Roberto Albuquerque\n"
        "Conceitos de criação de valor e decisões financeiras de longo prazo.",
        fontsize=16,
    )

    # Slide 2: Investment Analysis with LaTeX Equation
    page2 = doc.new_page(width=720, height=405)
    page2.insert_text(
        (50, 60),
        "# Valor Presente Líquido (VPL)\n"
        "Critério quantitativo para avaliação de fluxos de caixa descontados:\n"
        "$$\\text{VPL} = \\sum_{t=1}^n \\frac{FC_t}{(1 + r)^t} - I_0$$\n"
        "Regra: se VPL > 0, o projeto cria valor econômico.",
        fontsize=16,
    )

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def synthetic_pptx_path(tmp_path: Path) -> Path:
    """Creates a minimal synthetic PPTX file with 2 slides containing table and LaTeX.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        Path to the generated PPTX presentation.

    Raises:
        None.
    """
    pptx_path = tmp_path / "test_presentation.pptx"
    prs = pptx.Presentation()

    # Slide 1: Title slide
    title_layout = prs.slide_layouts[0]
    slide1 = prs.slides.add_slide(title_layout)
    if slide1.shapes.title:
        slide1.shapes.title.text = "Custo de Capital e Estrutura Financeira"
    subtitle = slide1.placeholders[1]
    subtitle.text = "Modelagem de WACC e CAPM para avaliação corporativa."

    # Slide 2: Slide with Table and LaTeX Equation
    content_layout = prs.slide_layouts[5]  # Title only
    slide2 = prs.slides.add_slide(content_layout)
    if slide2.shapes.title:
        slide2.shapes.title.text = "Parâmetros do Modelo WACC"

    # Add text frame with formula
    tx_box = slide2.shapes.add_textbox(50, 100, 600, 80)
    tx_box.text_frame.text = (
        "Fórmula do WACC:\n"
        "$$\\text{WACC} = "
        "\\left( \\frac{E}{V} \\right) K_e + \\left( \\frac{D}{V} \\right) K_d (1 - T)$$"
    )

    # Add 3x2 table
    table_shape = slide2.shapes.add_table(3, 2, 50, 200, 600, 150)
    table = table_shape.table
    table.cell(0, 0).text = "Parâmetro"
    table.cell(0, 1).text = "Valor Estimado"
    table.cell(1, 0).text = "Custo do Patrimônio Líquido (Ke)"
    table.cell(1, 1).text = "14.2%"
    table.cell(2, 0).text = "Custo da Dívida Líquido (Kd)"
    table.cell(2, 1).text = "8.5%"

    prs.save(str(pptx_path))
    return pptx_path


def test_parse_pdf_slides(synthetic_pdf_path: Path) -> None:
    """Tests parsing a PDF presentation into validated SlideChunk models.

    Args:
        synthetic_pdf_path: Path fixture to temporary test PDF.

    Returns:
        None.

    Raises:
        None.
    """
    chunks = parse_pdf_slides(synthetic_pdf_path)

    assert len(chunks) == 2
    assert all(isinstance(c, SlideChunk) for c in chunks)

    # Validate Slide 1
    assert chunks[0].slide_number == 1
    assert (
        "Finanças Corporativas" in chunks[0].title or "Finanças Corporativas" in chunks[0].raw_text
    )

    # Validate Slide 2
    assert chunks[1].slide_number == 2
    assert "Valor Presente Líquido" in chunks[1].title or "VPL" in chunks[1].raw_text
    assert len(chunks[1].latex_equations) >= 1
    assert any("\\text{VPL}" in eq for eq in chunks[1].latex_equations)


def test_parse_pptx_slides(synthetic_pptx_path: Path) -> None:
    """Tests parsing a PPTX presentation into validated SlideChunk models.

    Args:
        synthetic_pptx_path: Path fixture to temporary test PPTX.

    Returns:
        None.

    Raises:
        None.
    """
    chunks = parse_pptx_slides(synthetic_pptx_path)

    assert len(chunks) == 2
    assert all(isinstance(c, SlideChunk) for c in chunks)

    # Validate Slide 1
    assert chunks[0].slide_number == 1
    assert chunks[0].title == "Custo de Capital e Estrutura Financeira"

    # Validate Slide 2 with table and LaTeX
    assert chunks[1].slide_number == 2
    assert chunks[1].title == "Parâmetros do Modelo WACC"
    assert len(chunks[1].latex_equations) >= 1
    assert any("\\text{WACC}" in eq for eq in chunks[1].latex_equations)

    # Verify Markdown table preservation
    assert "| Parâmetro | Valor Estimado |" in chunks[1].raw_text
    assert "| --- | --- |" in chunks[1].raw_text
    assert "| Custo do Patrimônio Líquido (Ke) | 14.2% |" in chunks[1].raw_text


def test_parse_slides_dispatcher_pdf_and_pptx(
    synthetic_pdf_path: Path,
    synthetic_pptx_path: Path,
) -> None:
    """Tests parse_slides dispatcher function handling both PDF and PPTX extensions.

    Args:
        synthetic_pdf_path: Path fixture to temporary test PDF.
        synthetic_pptx_path: Path fixture to temporary test PPTX.

    Returns:
        None.

    Raises:
        None.
    """
    pdf_chunks = parse_slides(synthetic_pdf_path)
    assert len(pdf_chunks) == 2

    pptx_chunks = parse_slides(synthetic_pptx_path)
    assert len(pptx_chunks) == 2


def test_parse_slides_unsupported_format_raises(tmp_path: Path) -> None:
    """Tests that passing unsupported file extension raises ValueError.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.

    Raises:
        None.
    """
    bad_file = tmp_path / "slides.docx"
    bad_file.write_text("dummy", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported slide format"):
        parse_slides(bad_file)


def test_parse_slides_missing_file_raises(tmp_path: Path) -> None:
    """Tests that parsing non-existent file path raises FileNotFoundError.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.

    Raises:
        None.
    """
    missing = tmp_path / "missing_presentation.pptx"
    with pytest.raises(FileNotFoundError, match="Slide presentation file not found"):
        parse_slides(missing)


def test_extract_latex_equations_helper() -> None:
    """Tests regex extraction and isolation of display and inline LaTeX formulas.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    text = (
        "Considere o cálculo do VPL abaixo:\n"
        "$$\\text{VPL} = \\sum_{t=1}^n \\frac{FC_t}{(1 + r)^t} - I_0$$\n"
        "E o modelo CAPM onde $K_e = R_f + \\beta (R_m - R_f)$ representa o retorno."
    )
    equations = extract_latex_equations(text)
    assert len(equations) == 2
    assert any("\\text{VPL}" in eq for eq in equations)
    assert any("K_e = R_f" in eq for eq in equations)


def test_infer_slide_title_helper() -> None:
    """Tests inferring slide titles from markdown headings or first line.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    heading_text = "# Estrutura Ótima de Capital\nConteúdo sobre alavancagem."
    assert infer_slide_title(heading_text, "Slide 1") == "Estrutura Ótima de Capital"

    plain_text = "Teorema de Modigliani-Miller\nPremissas de mercado perfeito."
    assert infer_slide_title(plain_text, "Slide 2") == "Teorema de Modigliani-Miller"

    empty_text = "   \n\n  "
    assert infer_slide_title(empty_text, "Slide 3") == "Slide 3"


def test_extract_latex_equations_brackets_and_parentheses() -> None:
    """Tests extraction of LaTeX equations formatted with bracket and parenthesis delimiters.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    text = (
        r"Fórmula em colchetes: \[ \text{WACC} = \frac{E}{V} K_e \] "
        r"e inline com parênteses: \( r_i = r_f + \beta (r_m - r_f) \)."
    )
    equations = extract_latex_equations(text)
    assert len(equations) == 2
    assert any(r"\text{WACC}" in eq for eq in equations)
    assert any(r"r_i = r_f" in eq for eq in equations)


def test_table_to_markdown_empty_table() -> None:
    """Tests that table_to_markdown returns empty string when table has zero rows.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """

    class EmptyTable:
        """Mock table class with empty rows attribute."""

        rows: list[Any] = []

    assert table_to_markdown(EmptyTable()) == ""


def test_parse_pdf_slides_corrupted_file_raises(tmp_path: Path) -> None:
    """Tests that parse_pdf_slides raises RuntimeError when PDF file is invalid or corrupted.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    bad_pdf = tmp_path / "corrupted.pdf"
    bad_pdf.write_text("not a real pdf content", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Failed to extract PDF slides"):
        parse_pdf_slides(bad_pdf)


def test_parse_pptx_slides_corrupted_file_raises(tmp_path: Path) -> None:
    """Tests that parse_pptx_slides raises RuntimeError when PPTX file is corrupted.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    bad_pptx = tmp_path / "corrupted.pptx"
    bad_pptx.write_text("not a real pptx content", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Failed to load PPTX presentation"):
        parse_pptx_slides(bad_pptx)

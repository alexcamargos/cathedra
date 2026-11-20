"""Slide parser module for extracting academic slides from PDF and PPTX files.

Processes presentation slides page-by-page, converts embedded tabular data into
standard Markdown tables, and isolates mathematical formulas in LaTeX format
into validated SlideChunk schemas.
"""

import re
from pathlib import Path
from typing import Any

from cathedra.schemas import SlideChunk

# Regex patterns for detecting LaTeX mathematical formulas
RE_DISPLAY_LATEX = re.compile(r"\$\$([\s\S]+?)\$\$")
RE_BRACKET_LATEX = re.compile(r"\\\[([\s\S]+?)\\\]")
RE_INLINE_LATEX = re.compile(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)")
RE_PAREN_LATEX = re.compile(r"\\\(([\s\S]+?)\\\)")


def extract_latex_equations(text: str) -> list[str]:
    """Extracts and isolates distinct LaTeX mathematical formulas from text.

    Scans for display math ($$...$$ and \\[...\\]) and inline math ($...$ and \\(...\\)),
    strips extraneous whitespace, and returns an ordered list of unique equations.

    Args:
        text: Raw text or markdown string containing mathematical markup.

    Returns:
        List of unique LaTeX equation strings isolated from the text.

    Raises:
        None.
    """
    found_equations: list[str] = []

    # 1. Display math: $$...$$
    for match in RE_DISPLAY_LATEX.finditer(text):
        eq = match.group(1).strip()
        if eq and eq not in found_equations:
            found_equations.append(eq)

    # 2. Display math: \[...\]
    for match in RE_BRACKET_LATEX.finditer(text):
        eq = match.group(1).strip()
        if eq and eq not in found_equations:
            found_equations.append(eq)

    # 3. Inline math: $...$
    for match in RE_INLINE_LATEX.finditer(text):
        eq = match.group(1).strip()
        if eq and eq not in found_equations:
            found_equations.append(eq)

    # 4. Inline math: \(...\)
    for match in RE_PAREN_LATEX.finditer(text):
        eq = match.group(1).strip()
        if eq and eq not in found_equations:
            found_equations.append(eq)

    return found_equations


def infer_slide_title(text: str, default: str) -> str:
    """Infers the slide title from markdown headers or the leading text line.

    Args:
        text: Plain text or markdown content of the slide.
        default: Fallback title to use if no valid title line is detected.

    Returns:
        Inferred slide title string.

    Raises:
        None.
    """
    for line in text.splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue

        # Check for Markdown heading (# Title, ## Title, etc.)
        heading_match = re.match(r"^#+\s+(.+)$", trimmed)
        if heading_match:
            return heading_match.group(1).strip()

        # Fallback to the first non-empty text line
        return trimmed[:100].strip()

    return default


def table_to_markdown(table: Any) -> str:
    """Converts a PowerPoint tabular shape object into a GitHub Flavored Markdown table.

    Args:
        table: python-pptx Table object containing rows and cells.

    Returns:
        Markdown table string representation.

    Raises:
        None.
    """
    rows: list[list[str]] = []
    for row in table.rows:
        row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows.append(row_cells)

    if not rows:
        return ""

    num_cols = len(rows[0])
    lines: list[str] = []

    # Header row
    header = "| " + " | ".join(rows[0]) + " |"
    separator = "| " + " | ".join(["---"] * num_cols) + " |"
    lines.append(header)
    lines.append(separator)

    # Body rows
    for row_cells in rows[1:]:
        # Pad row if columns are missing
        padded = row_cells + [""] * (num_cols - len(row_cells))
        lines.append("| " + " | ".join(padded[:num_cols]) + " |")

    return "\n".join(lines)


def parse_pdf_slides(file_path: Path) -> list[SlideChunk]:
    """Extracts slides from a PDF file page by page using pymupdf4llm.

    Args:
        file_path: Absolute or relative Path pointing to the target PDF presentation.

    Returns:
        List of SlideChunk instances populated with extracted text, title, and LaTeX.

    Raises:
        FileNotFoundError: If the input file does not exist on disk.
        RuntimeError: If document opening or text extraction fails.
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Slide presentation file not found: {file_path}")

    try:
        import pymupdf
        import pymupdf4llm  # type: ignore[import-untyped]

        doc: Any = pymupdf.open(str(file_path))  # type: ignore[no-untyped-call]
    except Exception as exc:
        raise RuntimeError(f"Failed to extract PDF slides from {file_path}: {exc}") from exc

    try:
        chunks_data = pymupdf4llm.to_markdown(doc, page_chunks=True)
        results: list[SlideChunk] = []
        for idx, page_chunk in enumerate(chunks_data):
            slide_num = idx + 1
            raw_text: str = page_chunk.get("text", "").strip()
            title = infer_slide_title(raw_text, default=f"Slide {slide_num}")
            latex_equations = extract_latex_equations(raw_text)

            visual_descriptions: list[str] = []
            try:
                page = doc[idx]
                images = page.get_images()
                if images:
                    visual_descriptions.append(
                        f"{len(images)} elemento(s) visual(is) detectado(s) no slide {slide_num}."
                    )
            except Exception:
                pass

            results.append(
                SlideChunk(
                    slide_number=slide_num,
                    title=title,
                    raw_text=raw_text,
                    latex_equations=latex_equations,
                    visual_descriptions=visual_descriptions,
                )
            )
        return results
    finally:
        doc.close()


def parse_pptx_slides(file_path: Path) -> list[SlideChunk]:
    """Extracts slides from a PPTX file preserving tables in Markdown and isolating LaTeX.

    Args:
        file_path: Path pointing to the target PPTX presentation file.

    Returns:
        List of SlideChunk instances populated with extracted text, title, and LaTeX.

    Raises:
        FileNotFoundError: If the input file does not exist on disk.
        RuntimeError: If PPTX presentation loading or parsing fails.
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Slide presentation file not found: {file_path}")

    try:
        import pptx

        prs = pptx.Presentation(str(file_path))
    except Exception as exc:
        raise RuntimeError(f"Failed to load PPTX presentation from {file_path}: {exc}") from exc

    results: list[SlideChunk] = []

    for idx, slide in enumerate(prs.slides):
        slide_num = idx + 1

        # Extract title shape if available
        title_text = ""
        if slide.shapes.title and slide.shapes.title.has_text_frame:
            title_text = slide.shapes.title.text_frame.text.strip()

        content_blocks: list[str] = []
        visual_descriptions: list[str] = []

        for shape in slide.shapes:
            # Skip title shape as it is handled explicitly
            if shape == slide.shapes.title:
                continue

            # Check for tabular shape
            if shape.has_table:
                md_table = table_to_markdown(shape.table)
                if md_table:
                    content_blocks.append(md_table)
                continue

            # Check for regular text frame
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    content_blocks.append(text)
                continue

            # Record visual representation if shape is picture or graphic
            if hasattr(shape, "name") and shape.name:
                visual_descriptions.append(f"Elemento visual: {shape.name}")

        # Construct raw markdown text
        raw_parts: list[str] = []
        if title_text:
            raw_parts.append(f"# {title_text}")
        if content_blocks:
            raw_parts.append("\n\n".join(content_blocks))

        full_raw_text = "\n\n".join(raw_parts).strip()
        final_title = title_text or infer_slide_title(full_raw_text, default=f"Slide {slide_num}")
        latex_equations = extract_latex_equations(full_raw_text)

        results.append(
            SlideChunk(
                slide_number=slide_num,
                title=final_title,
                raw_text=full_raw_text,
                latex_equations=latex_equations,
                visual_descriptions=visual_descriptions,
            )
        )

    return results


def parse_slides(file_path: Path) -> list[SlideChunk]:
    """Unified dispatcher for parsing slides from PDF and PPTX presentations.

    Args:
        file_path: Path to presentation document (.pdf or .pptx).

    Returns:
        List of SlideChunk instances extracted from the document.

    Raises:
        FileNotFoundError: If target file does not exist on disk.
        ValueError: If file format is not .pdf or .pptx.
        RuntimeError: If extraction fails.
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Slide presentation file not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf_slides(file_path)
    if suffix == ".pptx":
        return parse_pptx_slides(file_path)

    raise ValueError(f"Unsupported slide format '{suffix}'. Supported formats are .pdf and .pptx.")


__all__ = [
    "extract_latex_equations",
    "infer_slide_title",
    "parse_pdf_slides",
    "parse_pptx_slides",
    "parse_slides",
    "table_to_markdown",
]

"""Document and slide ingestion package."""

from mba_wiki.ingestion.slide_parser import (
    extract_latex_equations,
    infer_slide_title,
    parse_pdf_slides,
    parse_pptx_slides,
    parse_slides,
    table_to_markdown,
)
from mba_wiki.ingestion.syllabus_parser import (
    get_syllabus_parser_prompt,
    load_structured_syllabus,
    parse_syllabus,
    process_and_save_syllabus,
    read_syllabus_source,
    save_structured_syllabus,
)

__all__ = [
    "extract_latex_equations",
    "get_syllabus_parser_prompt",
    "infer_slide_title",
    "load_structured_syllabus",
    "parse_pdf_slides",
    "parse_pptx_slides",
    "parse_slides",
    "parse_syllabus",
    "process_and_save_syllabus",
    "read_syllabus_source",
    "save_structured_syllabus",
    "table_to_markdown",
]

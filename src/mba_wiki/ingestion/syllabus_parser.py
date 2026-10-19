"""Parser for academic course syllabi and curricula.

Extracts text from syllabus source documents, queries a StructuredLLMClient to convert
unstructured course programs into validated Pydantic models, and manages persistence.
"""

from pathlib import Path

from mba_wiki.agents.llm_client import StructuredLLMClient
from mba_wiki.schemas import StructuredSyllabus

DEFAULT_PROMPT_PATH = Path(__file__).parent.parent / "agents" / "prompts" / "syllabus_parser.md"


def get_syllabus_parser_prompt(prompt_path: Path | None = None) -> str:
    """Loads the system prompt for syllabus extraction from external markdown file.

    Args:
        prompt_path: Optional explicit path to prompt file. Defaults to DEFAULT_PROMPT_PATH.

    Returns:
        String content of the prompt markdown file.

    Raises:
        FileNotFoundError: If the specified prompt file cannot be found on disk.
    """
    resolved_path = prompt_path or DEFAULT_PROMPT_PATH
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Syllabus parser prompt file not found: {resolved_path}")
    return resolved_path.read_text(encoding="utf-8")


def read_syllabus_source(file_path: Path) -> str:
    """Reads syllabus content from disk, supporting text, markdown, and PDF formats.

    Args:
        file_path: Path pointing to the source syllabus document.

    Returns:
        Extracted text or markdown content of the syllabus.

    Raises:
        FileNotFoundError: If the source file does not exist on disk.
        RuntimeError: If PDF extraction fails.
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Syllabus source file not found: {file_path}")

    if file_path.suffix.lower() == ".pdf":
        try:
            import pymupdf4llm  # type: ignore[import-untyped]

            extracted: str = pymupdf4llm.to_markdown(str(file_path))
            return extracted
        except Exception as exc:
            raise RuntimeError(f"Failed to extract PDF syllabus content: {exc}") from exc

    return file_path.read_text(encoding="utf-8")


def parse_syllabus(
    source_text: str,
    client: StructuredLLMClient,
    prompt: str | None = None,
) -> StructuredSyllabus:
    """Parses raw syllabus text into a validated StructuredSyllabus using StructuredLLMClient.

    Args:
        source_text: Plain text or markdown extracted from syllabus document.
        client: Concrete or mock implementation conforming to StructuredLLMClient protocol.
        prompt: Optional system prompt override. Defaults to dynamically loaded prompt.

    Returns:
        Validated StructuredSyllabus instance containing structured module schemas.

    Raises:
        Exception: If LLM generation or Pydantic validation fails.
    """
    system_prompt = prompt or get_syllabus_parser_prompt()
    structured: StructuredSyllabus = client.generate_structured(
        system_prompt=system_prompt,
        user_prompt=source_text,
        response_model=StructuredSyllabus,
    )
    return structured


def save_structured_syllabus(
    syllabus: StructuredSyllabus,
    destination_path: Path,
) -> Path:
    """Persists a validated StructuredSyllabus instance to disk as formatted JSON.

    Args:
        syllabus: Validated StructuredSyllabus instance to be written.
        destination_path: Target path for the output JSON file.

    Returns:
        The resolved destination path where the JSON was successfully saved.

    Raises:
        OSError: If file writing or directory creation fails.
    """
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(syllabus.model_dump_json(indent=2), encoding="utf-8")
    return destination_path


def load_structured_syllabus(json_path: Path) -> StructuredSyllabus:
    """Loads and validates a previously saved ementa_estruturada.json file.

    Args:
        json_path: Path to the JSON file on disk.

    Returns:
        A validated StructuredSyllabus instance.

    Raises:
        FileNotFoundError: If the specified file does not exist.
        pydantic.ValidationError: If the JSON structure fails schema validation.
    """
    if not json_path.is_file():
        raise FileNotFoundError(f"Structured syllabus file not found: {json_path}")

    raw_json = json_path.read_text(encoding="utf-8")
    return StructuredSyllabus.model_validate_json(raw_json)


def process_and_save_syllabus(
    source_path: Path,
    destination_path: Path,
    client: StructuredLLMClient,
) -> StructuredSyllabus:
    """Coordinates reading, parsing via LLM, and persisting structured syllabus.

    Args:
        source_path: Path to input syllabus document (txt, md, or pdf).
        destination_path: Target path for output ementa_estruturada.json.
        client: Concrete or mock implementation conforming to StructuredLLMClient protocol.

    Returns:
        The resulting validated StructuredSyllabus instance.

    Raises:
        FileNotFoundError: If source file is missing.
        Exception: If extraction, parsing, or file persistence fails.
    """
    raw_content = read_syllabus_source(source_path)
    structured = parse_syllabus(source_text=raw_content, client=client)
    save_structured_syllabus(syllabus=structured, destination_path=destination_path)
    return structured


__all__ = [
    "DEFAULT_PROMPT_PATH",
    "get_syllabus_parser_prompt",
    "load_structured_syllabus",
    "parse_syllabus",
    "process_and_save_syllabus",
    "read_syllabus_source",
    "save_structured_syllabus",
]

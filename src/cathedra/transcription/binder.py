"""Batch binding utility to align existing transcript JSONs with the structured syllabus.

Cross-references transcript subfolders, structured syllabus modules, numeric filename
prefixes, and optional slide decks to populate canonical discipline_slug and
lesson_number fields without invalidating existing transcription checkpoints.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from cathedra.schemas import StructuredSyllabus, VideoTranscript
from cathedra.transcription.batch_runner import _slugify, _write_transcript_atomically

_LESSON_PREFIX_RE = re.compile(r"^(\d+)(?:[-_\s]|$)")
_SUPPORTED_SLIDE_EXTENSIONS = {".pdf", ".pptx"}


@dataclass(frozen=True)
class BoundTranscriptItem:
    """Represents a transcript JSON file updated (or planned) during binding.

    Attributes:
        file_path: Filesystem path to the transcript JSON file.
        discipline_slug: Canonical discipline slug assigned from the syllabus.
        lesson_number: Extracted sequential lesson number.
        previous_discipline_slug: Discipline slug before binding.
        previous_lesson_number: Lesson number before binding.
    """

    file_path: Path
    discipline_slug: str
    lesson_number: int
    previous_discipline_slug: str
    previous_lesson_number: int | None


@dataclass
class TranscriptBindSummary:
    """Execution summary produced by batch transcript-to-syllabus binding.

    Attributes:
        total_files_scanned: Total transcript JSON files inspected in matched folders.
        updated_files: Transcript items updated (or planned in dry-run mode).
        already_bound_count: Count of files already matching canonical slug and lesson number.
        unmatched_folders: Transcript subfolders with no matching syllabus discipline.
        unnumbered_files: Relative paths of files missing a leading numeric prefix.
        ambiguous_files: Relative paths of files sharing a duplicate lesson number.
        invalid_files: Relative paths of files that failed JSON/schema validation.
        warnings: Non-fatal alignment warnings (such as missing matching slides).
    """

    total_files_scanned: int = 0
    updated_files: list[BoundTranscriptItem] = field(default_factory=list)
    already_bound_count: int = 0
    unmatched_folders: list[str] = field(default_factory=list)
    unnumbered_files: list[str] = field(default_factory=list)
    ambiguous_files: list[str] = field(default_factory=list)
    invalid_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def extract_lesson_number(stem: str) -> int | None:
    """Extracts a positive integer lesson number from a filename stem prefix.

    Args:
        stem: Filename stem without extension (e.g. '01-Fundamentos-de-Estatistica-I').

    Returns:
        Positive integer lesson number if a valid leading prefix exists, otherwise None.

    Raises:
        None.
    """
    match = _LESSON_PREFIX_RE.match(stem.strip())
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def _build_syllabus_lookup(syllabus: StructuredSyllabus) -> dict[str, str]:
    """Maps normalized folder/slug variants to canonical syllabus discipline slugs.

    Args:
        syllabus: Structured course syllabus containing ordered discipline modules.

    Returns:
        Dictionary mapping normalized slug keys to canonical discipline_slug values.

    Raises:
        None.
    """
    lookup: dict[str, str] = {}
    for module in syllabus.modules:
        lookup[module.discipline_slug] = module.discipline_slug
        lookup[_slugify(module.discipline_slug)] = module.discipline_slug
        lookup[_slugify(module.discipline_name)] = module.discipline_slug
    return lookup


def _collect_slide_numbers(slides_dir: Path | None, discipline_slug: str) -> set[int] | None:
    """Collects numeric lesson prefixes present in a discipline's slides directory.

    Args:
        slides_dir: Optional root directory containing per-discipline slide folders.
        discipline_slug: Canonical discipline slug to inspect.

    Returns:
        Set of extracted lesson numbers if the discipline slide folder exists, else None.

    Raises:
        None.
    """
    if slides_dir is None:
        return None
    discipline_slides = slides_dir / discipline_slug
    if not discipline_slides.is_dir():
        return None
    numbers: set[int] = set()
    for item in discipline_slides.iterdir():
        if item.is_file() and item.suffix.lower() in _SUPPORTED_SLIDE_EXTENSIONS:
            num = extract_lesson_number(item.stem)
            if num is not None:
                numbers.add(num)
    return numbers


def _process_discipline_folder(
    folder: Path,
    canonical_slug: str,
    transcripts_dir: Path,
    slides_dir: Path | None,
    dry_run: bool,
    summary: TranscriptBindSummary,
) -> None:
    """Processes all transcript JSONs inside a single syllabus-matched discipline folder.

    Args:
        folder: Discipline transcript directory on disk.
        canonical_slug: Canonical discipline_slug from the structured syllabus.
        transcripts_dir: Root transcripts directory (for relative paths and history).
        slides_dir: Optional root slides directory for cross-reference warnings.
        dry_run: When True, records planned updates without writing to disk.
        summary: Mutable TranscriptBindSummary accumulator.

    Returns:
        None.

    Raises:
        None.
    """
    parsed_entries: list[tuple[Path, VideoTranscript, bytes, int | None]] = []
    number_counts: dict[int, int] = {}

    for json_path in sorted(folder.glob("*.json")):
        if not json_path.is_file():
            continue
        summary.total_files_scanned += 1
        try:
            raw_bytes = json_path.read_bytes()
            transcript = VideoTranscript.model_validate_json(raw_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            summary.invalid_files.append(str(json_path.relative_to(transcripts_dir)))
            continue

        lesson_num = extract_lesson_number(json_path.stem)
        if lesson_num is None:
            summary.unnumbered_files.append(str(json_path.relative_to(transcripts_dir)))
            continue

        number_counts[lesson_num] = number_counts.get(lesson_num, 0) + 1
        parsed_entries.append((json_path, transcript, raw_bytes, lesson_num))

    slide_numbers = _collect_slide_numbers(slides_dir, canonical_slug)
    history_dir = transcripts_dir / ".history" / canonical_slug

    for json_path, transcript, raw_bytes, lesson_num in parsed_entries:
        if lesson_num is None:
            continue
        if number_counts[lesson_num] > 1:
            summary.ambiguous_files.append(str(json_path.relative_to(transcripts_dir)))
            continue

        if slide_numbers is not None and lesson_num not in slide_numbers:
            summary.warnings.append(
                f"{canonical_slug}: transcrição {json_path.name} (aula {lesson_num:02d}) "
                "sem slide correspondente."
            )

        if transcript.discipline_slug == canonical_slug and transcript.lesson_number == lesson_num:
            summary.already_bound_count += 1
            continue

        item = BoundTranscriptItem(
            file_path=json_path,
            discipline_slug=canonical_slug,
            lesson_number=lesson_num,
            previous_discipline_slug=transcript.discipline_slug,
            previous_lesson_number=transcript.lesson_number,
        )
        if not dry_run:
            updated = transcript.model_copy(
                update={"discipline_slug": canonical_slug, "lesson_number": lesson_num}
            )
            _write_transcript_atomically(json_path, updated, raw_bytes, history_dir)
        summary.updated_files.append(item)


def bind_transcripts_to_syllabus(
    syllabus: StructuredSyllabus,
    transcripts_dir: Path,
    slides_dir: Path | None = None,
    dry_run: bool = False,
) -> TranscriptBindSummary:
    """Binds existing transcript JSONs to canonical syllabus slugs and lesson numbers.

    Args:
        syllabus: Loaded StructuredSyllabus defining valid course disciplines.
        transcripts_dir: Root directory containing per-discipline transcript folders.
        slides_dir: Optional root slides directory for cross-checking lesson numbers.
        dry_run: If True, simulates binding without modifying files on disk.

    Returns:
        TranscriptBindSummary detailing updated, skipped, unmatched, and ambiguous items.

    Raises:
        FileNotFoundError: If transcripts_dir does not exist.
    """
    if not transcripts_dir.is_dir():
        raise FileNotFoundError(f"Diretório de transcrições não encontrado: {transcripts_dir}")

    lookup = _build_syllabus_lookup(syllabus)
    summary = TranscriptBindSummary()

    for entry in sorted(transcripts_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        canonical_slug = lookup.get(entry.name) or lookup.get(_slugify(entry.name))
        if canonical_slug is None:
            summary.unmatched_folders.append(entry.name)
            continue
        _process_discipline_folder(
            folder=entry,
            canonical_slug=canonical_slug,
            transcripts_dir=transcripts_dir,
            slides_dir=slides_dir,
            dry_run=dry_run,
            summary=summary,
        )

    return summary

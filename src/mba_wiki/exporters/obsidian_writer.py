"""Idempotent Obsidian Vault exporter module.

Persists and updates lesson wiki pages, discipline indices (MOCs), atomic Zettelkasten
notes, and factual audit JSON reports while preserving manual human notes and preventing
link duplication across re-runs.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from mba_wiki.schemas import (
    AtomicZettel,
    LessonAuditReport,
    SyllabusModule,
    WikiLessonOutput,
)

AUTO_LESSONS_START = "<!-- AUTO-LESSONS:START -->"
AUTO_LESSONS_END = "<!-- AUTO-LESSONS:END -->"
AUTO_CONTENT_START = "<!-- AUTO-CONTENT:START -->"
AUTO_CONTENT_END = "<!-- AUTO-CONTENT:END -->"
AUTO_BACKLINKS_START = "<!-- AUTO-BACKLINKS:START -->"
AUTO_BACKLINKS_END = "<!-- AUTO-BACKLINKS:END -->"


@dataclass
class VaultExportResult:
    """Consolidated filesystem paths of all artifacts exported to the Obsidian Vault.

    Attributes:
        lesson_path: Path to the generated or updated wiki lesson Markdown page.
        index_path: Path to the discipline index MOC (_Indice_Materia.md).
        zettel_paths: List of paths to exported or updated atomic Zettelkasten notes.
        audit_report_path: Path to the saved factual audit JSON report.
    """

    lesson_path: Path
    index_path: Path
    zettel_paths: list[Path]
    audit_report_path: Path


def write_discipline_index(
    vault_root: Path,
    syllabus: SyllabusModule,
    output: WikiLessonOutput,
) -> Path:
    """Generates or updates the discipline index MOC (_Indice_Materia.md) idempotently.

    Updates only the lesson list between AUTO-LESSONS delimiters, sorting lessons
    numerically and preserving any manual notes outside of the delimiters.

    Args:
        vault_root: Root directory of the target Obsidian Vault.
        syllabus: Anchoring SyllabusModule providing discipline metadata.
        output: Processed WikiLessonOutput with current lesson details.

    Returns:
        Path to the written or updated _Indice_Materia.md file.

    Raises:
        ValueError: If delimiters are missing in an existing index file.
    """
    discipline_dir = vault_root / "01_Wiki_Disciplinas" / syllabus.discipline_slug
    discipline_dir.mkdir(parents=True, exist_ok=True)
    index_path = discipline_dir / "_Indice_Materia.md"

    lesson_entry = (
        f"- [[Aula_{output.lesson_number:02d}_{output.lesson_slug}|"
        f"Aula {output.lesson_number:02d}: {output.lesson_title}]]"
    )

    if not index_path.is_file():
        bib_lines = "\n".join(f"- {item}" for item in syllabus.bibliography)
        content = (
            "---\n"
            "type: moc_disciplina\n"
            f'discipline_slug: "{syllabus.discipline_slug}"\n'
            f'discipline_name: "{syllabus.discipline_name}"\n'
            f'professor: "{syllabus.professor or ""}"\n'
            "tags:\n"
            "  - mba/disciplina\n"
            f"  - mba/{syllabus.discipline_slug}\n"
            "---\n\n"
            f"# {syllabus.discipline_name}\n\n"
            "## Ementa e Objetivos\n"
            f"{syllabus.syllabus_summary}\n\n"
            "## Aulas Processadas\n"
            f"{AUTO_LESSONS_START}\n"
            f"{lesson_entry}\n"
            f"{AUTO_LESSONS_END}\n\n"
            "## Bibliografia Oficial\n"
            f"{bib_lines}\n"
        )
        index_path.write_text(content, encoding="utf-8")
        return index_path

    existing_content = index_path.read_text(encoding="utf-8")
    start_idx = existing_content.find(AUTO_LESSONS_START)
    end_idx = existing_content.find(AUTO_LESSONS_END)

    if start_idx == -1 or end_idx == -1:
        raise ValueError(
            f"Delimiters '{AUTO_LESSONS_START}' and '{AUTO_LESSONS_END}' not found in {index_path}"
        )

    before_block = existing_content[: start_idx + len(AUTO_LESSONS_START)]
    inside_block = existing_content[start_idx + len(AUTO_LESSONS_START) : end_idx]
    after_block = existing_content[end_idx:]

    lesson_map: dict[int, str] = {}
    pattern = re.compile(r"- \[\[Aula_(\d+)_([^|]+)\|Aula \d+: ([^\]]+)\]\]")

    for raw_line in inside_block.splitlines():
        line = raw_line.strip()
        match = pattern.match(line)
        if match:
            num = int(match.group(1))
            lesson_map[num] = line

    lesson_map[output.lesson_number] = lesson_entry
    sorted_numbers = sorted(lesson_map.keys())
    new_lessons_content = "\n" + "\n".join(lesson_map[n] for n in sorted_numbers) + "\n"

    updated_content = f"{before_block}{new_lessons_content}{after_block}"
    index_path.write_text(updated_content, encoding="utf-8")
    return index_path


def format_zettels_section(zettels: list[AtomicZettel]) -> str:
    """Formats the related conceptual zettels section for a lesson wiki page.

    Args:
        zettels: List of extracted AtomicZettel candidate instances.

    Returns:
        Formatted Markdown section with wiki links.

    Raises:
        None.
    """
    if not zettels:
        return ""
    lines = ["## Conceitos Atomicos Relacionados"]
    lines.extend(f"- [[{zettel.slug}|{zettel.title}]]" for zettel in zettels)
    return "\n".join(lines)


def write_lesson_page(
    vault_root: Path,
    output: WikiLessonOutput,
) -> Path:
    """Writes or idempotently updates a lesson wiki page (Aula_NN_slug.md).

    Replaces content strictly within AUTO-CONTENT delimiters, ensuring personal
    notes in subsequent sections remain fully preserved.

    Args:
        vault_root: Target Obsidian Vault root directory.
        output: Completed WikiLessonOutput containing validated lesson data.

    Returns:
        Path to the saved or updated lesson Markdown file.

    Raises:
        ValueError: If delimiters are missing in an existing lesson file.
    """
    discipline_dir = vault_root / "01_Wiki_Disciplinas" / output.discipline_slug
    discipline_dir.mkdir(parents=True, exist_ok=True)
    filename = f"Aula_{output.lesson_number:02d}_{output.lesson_slug}.md"
    lesson_path = discipline_dir / filename

    zettel_block = format_zettels_section(output.extracted_zettels)
    auto_body = output.body_markdown.strip()
    if zettel_block:
        auto_body = f"{auto_body}\n\n{zettel_block}"

    if not lesson_path.is_file():
        content = (
            "---\n"
            "type: wiki_aula\n"
            f'discipline_slug: "{output.discipline_slug}"\n'
            f'discipline_name: "{output.discipline_name}"\n'
            f"lesson_number: {output.lesson_number}\n"
            f'lesson_title: "{output.lesson_title}"\n'
            f'lesson_slug: "{output.lesson_slug}"\n'
            f"processed_date: {output.processed_date.isoformat()}\n"
            f'source_slide: "{output.source_slide_filename}"\n'
            f"fact_check_passed: {str(output.fact_check_passed).lower()}\n"
            f"removed_claims: {output.removed_unsupported_claims}\n"
            "tags:\n"
            "  - mba/aula\n"
            f"  - mba/{output.discipline_slug}\n"
            "---\n\n"
            f"# Aula {output.lesson_number:02d}: {output.lesson_title}\n\n"
            "> [!info] Contexto da Disciplina\n"
            f"> Parte de [[01_Wiki_Disciplinas/{output.discipline_slug}/_Indice_Materia|"
            f"{output.discipline_name}]] | Slide base: `{output.source_slide_filename}`\n\n"
            f"{AUTO_CONTENT_START}\n"
            f"{auto_body}\n"
            f"{AUTO_CONTENT_END}\n\n"
            "---\n"
            "## Notas Pessoais de Aula\n"
            "<!-- Espaco preservado em reprocessamentos -->\n"
        )
        lesson_path.write_text(content, encoding="utf-8")
        return lesson_path

    existing_content = lesson_path.read_text(encoding="utf-8")
    start_idx = existing_content.find(AUTO_CONTENT_START)
    end_idx = existing_content.find(AUTO_CONTENT_END)

    if start_idx == -1 or end_idx == -1:
        raise ValueError(
            f"Delimiters '{AUTO_CONTENT_START}' and '{AUTO_CONTENT_END}' not found in {lesson_path}"
        )

    after_block = existing_content[end_idx + len(AUTO_CONTENT_END) :]

    # Update frontmatter metadata while preserving manual trailing notes
    new_header = (
        "---\n"
        "type: wiki_aula\n"
        f'discipline_slug: "{output.discipline_slug}"\n'
        f'discipline_name: "{output.discipline_name}"\n'
        f"lesson_number: {output.lesson_number}\n"
        f'lesson_title: "{output.lesson_title}"\n'
        f'lesson_slug: "{output.lesson_slug}"\n'
        f"processed_date: {output.processed_date.isoformat()}\n"
        f'source_slide: "{output.source_slide_filename}"\n'
        f"fact_check_passed: {str(output.fact_check_passed).lower()}\n"
        f"removed_claims: {output.removed_unsupported_claims}\n"
        "tags:\n"
        "  - mba/aula\n"
        f"  - mba/{output.discipline_slug}\n"
        "---\n\n"
        f"# Aula {output.lesson_number:02d}: {output.lesson_title}\n\n"
        "> [!info] Contexto da Disciplina\n"
        f"> Parte de [[01_Wiki_Disciplinas/{output.discipline_slug}/_Indice_Materia|"
        f"{output.discipline_name}]] | Slide base: `{output.source_slide_filename}`\n\n"
        f"{AUTO_CONTENT_START}\n"
        f"{auto_body}\n"
        f"{AUTO_CONTENT_END}"
    )

    updated_content = f"{new_header}{after_block}"
    lesson_path.write_text(updated_content, encoding="utf-8")
    return lesson_path


def write_atomic_zettel(
    vault_root: Path,
    zettel: AtomicZettel,
    output: WikiLessonOutput,
) -> Path:
    """Writes or idempotently updates an atomic note in 02_Zettelkasten.

    Preserves existing conceptual text, merges domain tags without duplicates,
    and records course backlink inside AUTO-BACKLINKS delimiters.

    Args:
        vault_root: Target Obsidian Vault root directory.
        zettel: Atomic conceptual note model to persist.
        output: WikiLessonOutput providing context for course backlinking.

    Returns:
        Path to the saved or updated Zettel Markdown file.

    Raises:
        ValueError: If delimiters are missing in an existing Zettel file.
    """
    zettel_dir = vault_root / "02_Zettelkasten"
    zettel_dir.mkdir(parents=True, exist_ok=True)
    zettel_path = zettel_dir / f"{zettel.slug}.md"

    lesson_backlink = (
        f"- [[Aula_{output.lesson_number:02d}_{output.lesson_slug}]] ({output.discipline_name})"
    )

    if not zettel_path.is_file():
        tag_lines = "\n".join(f"  - {tag}" for tag in zettel.domain_tags)
        direct_link_lines = "\n".join(f"- [[{link}]]" for link in zettel.related_links)
        content = (
            "---\n"
            "type: zettel\n"
            f'slug: "{zettel.slug}"\n'
            f'title: "{zettel.title}"\n'
            "tags:\n"
            f"{tag_lines}\n"
            "---\n\n"
            f"# {zettel.title}\n\n"
            f"{zettel.content_markdown}\n\n"
            "## Conexoes Diretas\n"
            f"{direct_link_lines}\n\n"
            "## Referencias no Curso\n"
            f"{AUTO_BACKLINKS_START}\n"
            f"{lesson_backlink}\n"
            f"{AUTO_BACKLINKS_END}\n"
        )
        zettel_path.write_text(content, encoding="utf-8")
        return zettel_path

    existing_content = zettel_path.read_text(encoding="utf-8")
    start_idx = existing_content.find(AUTO_BACKLINKS_START)
    end_idx = existing_content.find(AUTO_BACKLINKS_END)

    if start_idx == -1 or end_idx == -1:
        raise ValueError(
            f"Delimiters '{AUTO_BACKLINKS_START}' and '{AUTO_BACKLINKS_END}' "
            f"not found in {zettel_path}"
        )

    # 1. Merge domain tags into frontmatter without duplicates
    fm_match = re.match(r"^---\n(.*?)\n---\n", existing_content, re.DOTALL)
    existing_tags: list[str] = []
    if fm_match:
        fm_text = fm_match.group(1)
        tags_section = re.search(r"tags:\n((?:\s+-\s+[^\n]+\n?)+)", fm_text)
        if tags_section:
            for line in tags_section.group(1).splitlines():
                t = line.strip().lstrip("-").strip()
                if t and t not in existing_tags:
                    existing_tags.append(t)

    for new_tag in zettel.domain_tags:
        if new_tag not in existing_tags:
            existing_tags.append(new_tag)

    merged_tags_str = "\n".join(f"  - {tag}" for tag in existing_tags)
    new_fm = (
        "---\n"
        "type: zettel\n"
        f'slug: "{zettel.slug}"\n'
        f'title: "{zettel.title}"\n'
        "tags:\n"
        f"{merged_tags_str}\n"
        "---\n"
    )

    body_and_links = (
        existing_content[fm_match.end() : start_idx] if fm_match else existing_content[:start_idx]
    )

    # 2. Merge backlinks inside AUTO-BACKLINKS block
    inside_block = existing_content[start_idx + len(AUTO_BACKLINKS_START) : end_idx]
    existing_backlinks: list[str] = [
        line.strip() for line in inside_block.splitlines() if line.strip()
    ]

    if lesson_backlink not in existing_backlinks:
        existing_backlinks.append(lesson_backlink)

    new_backlinks_content = "\n" + "\n".join(existing_backlinks) + "\n"
    after_block = existing_content[end_idx:]

    updated_content = (
        f"{new_fm}{body_and_links}{AUTO_BACKLINKS_START}{new_backlinks_content}{after_block}"
    )
    zettel_path.write_text(updated_content, encoding="utf-8")
    return zettel_path


def write_audit_report(
    vault_root: Path,
    output: WikiLessonOutput,
) -> Path:
    """Persists factual audit logs to 03_Auditoria_Factual as formatted JSON.

    Args:
        vault_root: Target Obsidian Vault root directory.
        output: Completed WikiLessonOutput containing audited claims and metrics.

    Returns:
        Path to the written audit JSON report file.

    Raises:
        OSError: If directory creation or file writing fails.
    """
    audit_dir = vault_root / "03_Auditoria_Factual"
    audit_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{output.discipline_slug}_Aula_{output.lesson_number:02d}_audit.json"
    report_path = audit_dir / filename

    report = LessonAuditReport(
        discipline_slug=output.discipline_slug,
        discipline_name=output.discipline_name,
        lesson_number=output.lesson_number,
        lesson_title=output.lesson_title,
        processed_date=output.processed_date,
        fact_check_passed=output.fact_check_passed,
        total_claims_audited=len(output.audit_items),
        removed_unsupported_claims=output.removed_unsupported_claims,
        audit_items=output.audit_items,
    )

    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report_path


def export_lesson_to_vault(
    vault_root: Path,
    output: WikiLessonOutput,
    syllabus: SyllabusModule,
) -> VaultExportResult:
    """Coordinates idempotent export of all lesson artifacts to the Obsidian Vault.

    Executes write_lesson_page, write_discipline_index, write_atomic_zettel for all
    extracted concepts, and write_audit_report.

    Args:
        vault_root: Target Obsidian Vault root directory.
        output: Validated WikiLessonOutput to persist.
        syllabus: Anchoring SyllabusModule for discipline metadata.

    Returns:
        VaultExportResult consolidating paths of all exported files.

    Raises:
        ValueError: If file delimiters are damaged or missing during updates.
        OSError: If filesystem operations fail.
    """
    lesson_path = write_lesson_page(vault_root=vault_root, output=output)
    index_path = write_discipline_index(vault_root=vault_root, syllabus=syllabus, output=output)

    zettel_paths: list[Path] = []
    for zettel in output.extracted_zettels:
        z_path = write_atomic_zettel(vault_root=vault_root, zettel=zettel, output=output)
        zettel_paths.append(z_path)

    audit_path = write_audit_report(vault_root=vault_root, output=output)

    return VaultExportResult(
        lesson_path=lesson_path,
        index_path=index_path,
        zettel_paths=zettel_paths,
        audit_report_path=audit_path,
    )


__all__ = [
    "AUTO_BACKLINKS_END",
    "AUTO_BACKLINKS_START",
    "AUTO_CONTENT_END",
    "AUTO_CONTENT_START",
    "AUTO_LESSONS_END",
    "AUTO_LESSONS_START",
    "VaultExportResult",
    "export_lesson_to_vault",
    "format_zettels_section",
    "write_atomic_zettel",
    "write_audit_report",
    "write_discipline_index",
    "write_lesson_page",
]

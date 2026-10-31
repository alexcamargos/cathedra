"""Idempotent Obsidian Vault exporter module.

Persists and updates lesson wiki pages, discipline indices (MOCs), atomic Zettelkasten
notes, and factual audit JSON reports while preserving manual human notes and preventing
link duplication across re-runs.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from mba_wiki.schemas import (
    AtomicZettel,
    DialecticalTension,
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
AUTO_TENSIONS_START = "<!-- AUTO-TENSIONS:START -->"
AUTO_TENSIONS_END = "<!-- AUTO-TENSIONS:END -->"
AUTO_EVIDENCES_START = "<!-- AUTO-EVIDENCES:START -->"
AUTO_EVIDENCES_END = "<!-- AUTO-EVIDENCES:END -->"
AUTO_ZETTELS_START = "<!-- AUTO-ZETTELS:START -->"
AUTO_ZETTELS_END = "<!-- AUTO-ZETTELS:END -->"


def escape_yaml_str(text: str) -> str:
    """Escapes backslashes and double quotes for safe inclusion in YAML frontmatter.

    Args:
        text: Raw string value to escape.

    Returns:
        Escaped string safe for double-quoted YAML strings.

    Raises:
        None.
    """
    return text.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class VaultExportResult:
    """Consolidated filesystem paths of all artifacts exported to the Obsidian Vault.

    Attributes:
        lesson_path: Path to the generated or updated wiki lesson Markdown page.
        index_path: Path to the discipline index MOC (_Indice_Materia.md).
        zettel_paths: List of paths to exported or updated atomic Zettelkasten notes.
        audit_report_path: Path to the saved factual audit JSON report.
        tension_paths: List of paths to exported or updated dialectical tension notes.
        tensions_index_path: Path to the tensions index MOC (_Indice_Tensoes.md), if exported.
    """

    lesson_path: Path
    index_path: Path
    zettel_paths: list[Path]
    audit_report_path: Path
    tension_paths: list[Path] = field(default_factory=list)
    tensions_index_path: Path | None = None


def write_discipline_index(
    vault_root: Path,
    syllabus: SyllabusModule,
    output: WikiLessonOutput,
    force: bool = False,
) -> Path:
    """Generates or updates the discipline index MOC (_Indice_Materia.md) idempotently.

    Updates only the lesson list between AUTO-LESSONS delimiters, sorting lessons
    numerically and preserving any manual notes outside of the delimiters.

    Args:
        vault_root: Root directory of the target Obsidian Vault.
        syllabus: Anchoring SyllabusModule providing discipline metadata.
        output: Processed WikiLessonOutput with current lesson details.
        force: Whether to auto-recover missing delimiters instead of raising ValueError.

    Returns:
        Path to the written or updated _Indice_Materia.md file.

    Raises:
        ValueError: If delimiters are missing in an existing index file and force=False.
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
            f'discipline_slug: "{escape_yaml_str(syllabus.discipline_slug)}"\n'
            f'discipline_name: "{escape_yaml_str(syllabus.discipline_name)}"\n'
            f'professor: "{escape_yaml_str(syllabus.professor or "")}"\n'
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
        if not force:
            raise ValueError(
                f"Delimiters '{AUTO_LESSONS_START}' and '{AUTO_LESSONS_END}' "
                f"not found in {index_path}"
            )
        # Auto-heal: Recreate delimiters while preserving manual content
        if "## Aulas Processadas" in existing_content:
            pattern = re.compile(r"## Aulas Processadas.*?(?=\n## |\Z)", re.DOTALL)
            healed = (
                f"## Aulas Processadas\n{AUTO_LESSONS_START}\n{lesson_entry}\n{AUTO_LESSONS_END}\n"
            )
            updated_content = pattern.sub(healed, existing_content)
        else:
            updated_content = (
                existing_content.rstrip()
                + f"\n\n## Aulas Processadas\n{AUTO_LESSONS_START}\n{lesson_entry}\n"
                f"{AUTO_LESSONS_END}\n"
            )
        index_path.write_text(updated_content, encoding="utf-8")
        return index_path

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
    force: bool = False,
) -> Path:
    """Writes or idempotently updates a lesson wiki page (Aula_NN_slug.md).

    Replaces content strictly within AUTO-CONTENT delimiters, ensuring personal
    notes in subsequent sections remain fully preserved.

    Args:
        vault_root: Target Obsidian Vault root directory.
        output: Completed WikiLessonOutput containing validated lesson data.
        force: Whether to auto-recover missing delimiters instead of raising ValueError.

    Returns:
        Path to the saved or updated lesson Markdown file.

    Raises:
        ValueError: If delimiters are missing in an existing lesson file and force=False.
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
            f'discipline_slug: "{escape_yaml_str(output.discipline_slug)}"\n'
            f'discipline_name: "{escape_yaml_str(output.discipline_name)}"\n'
            f"lesson_number: {output.lesson_number}\n"
            f'lesson_title: "{escape_yaml_str(output.lesson_title)}"\n'
            f'lesson_slug: "{escape_yaml_str(output.lesson_slug)}"\n'
            f"processed_date: {output.processed_date.isoformat()}\n"
            f'source_slide: "{escape_yaml_str(output.source_slide_filename)}"\n'
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
        if not force:
            raise ValueError(
                f"Delimiters '{AUTO_CONTENT_START}' and '{AUTO_CONTENT_END}' "
                f"not found in {lesson_path}"
            )
        notes_marker = "## Notas Pessoais de Aula"
        marker_idx = existing_content.find(notes_marker)
        if marker_idx != -1:
            preserved_manual = existing_content[marker_idx:]
        else:
            preserved_manual = f"{notes_marker}\n<!-- Espaco preservado em reprocessamentos -->\n"

        new_header = (
            "---\n"
            "type: wiki_aula\n"
            f'discipline_slug: "{escape_yaml_str(output.discipline_slug)}"\n'
            f'discipline_name: "{escape_yaml_str(output.discipline_name)}"\n'
            f"lesson_number: {output.lesson_number}\n"
            f'lesson_title: "{escape_yaml_str(output.lesson_title)}"\n'
            f'lesson_slug: "{escape_yaml_str(output.lesson_slug)}"\n'
            f"processed_date: {output.processed_date.isoformat()}\n"
            f'source_slide: "{escape_yaml_str(output.source_slide_filename)}"\n'
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
        )
        updated_content = f"{new_header}{preserved_manual}"
        lesson_path.write_text(updated_content, encoding="utf-8")
        return lesson_path

    after_block = existing_content[end_idx + len(AUTO_CONTENT_END) :]

    # Update frontmatter metadata while preserving manual trailing notes
    new_header = (
        "---\n"
        "type: wiki_aula\n"
        f'discipline_slug: "{escape_yaml_str(output.discipline_slug)}"\n'
        f'discipline_name: "{escape_yaml_str(output.discipline_name)}"\n'
        f"lesson_number: {output.lesson_number}\n"
        f'lesson_title: "{escape_yaml_str(output.lesson_title)}"\n'
        f'lesson_slug: "{escape_yaml_str(output.lesson_slug)}"\n'
        f"processed_date: {output.processed_date.isoformat()}\n"
        f'source_slide: "{escape_yaml_str(output.source_slide_filename)}"\n'
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
    force: bool = False,
) -> Path:
    """Writes or idempotently updates an atomic note in 02_Zettelkasten.

    Preserves existing conceptual text, merges domain tags without duplicates,
    and records course backlink inside AUTO-BACKLINKS delimiters.

    Args:
        vault_root: Target Obsidian Vault root directory.
        zettel: Atomic conceptual note model to persist.
        output: WikiLessonOutput providing context for course backlinking.
        force: Whether to auto-recover missing delimiters instead of raising ValueError.

    Returns:
        Path to the saved or updated Zettel Markdown file.

    Raises:
        ValueError: If delimiters are missing in an existing Zettel file and force=False.
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
            f'slug: "{escape_yaml_str(zettel.slug)}"\n'
            f'title: "{escape_yaml_str(zettel.title)}"\n'
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
        if not force:
            raise ValueError(
                f"Delimiters '{AUTO_BACKLINKS_START}' and '{AUTO_BACKLINKS_END}' "
                f"not found in {zettel_path}"
            )
        if "## Referencias no Curso" in existing_content:
            pattern = re.compile(r"## Referencias no Curso.*?(?=\n## |\Z)", re.DOTALL)
            healed_block = (
                f"## Referencias no Curso\n{AUTO_BACKLINKS_START}\n"
                f"{lesson_backlink}\n{AUTO_BACKLINKS_END}\n"
            )
            updated_content = pattern.sub(healed_block, existing_content)
        else:
            updated_content = (
                existing_content.rstrip() + f"\n\n## Referencias no Curso\n{AUTO_BACKLINKS_START}\n"
                f"{lesson_backlink}\n{AUTO_BACKLINKS_END}\n"
            )
        zettel_path.write_text(updated_content, encoding="utf-8")
        return zettel_path

    # 1. Merge domain tags into frontmatter without duplicates
    fm_match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", existing_content, re.DOTALL)
    existing_tags: list[str] = []
    if fm_match:
        fm_text = fm_match.group(1)
        tags_section = re.search(r"tags:\r?\n((?:\s+-\s+[^\n]+\r?\n?)+)", fm_text)
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
        f'slug: "{escape_yaml_str(zettel.slug)}"\n'
        f'title: "{escape_yaml_str(zettel.title)}"\n'
        "tags:\n"
        f"{merged_tags_str}\n"
        "---\n"
    )

    body_and_links = (
        existing_content[fm_match.end() : start_idx] if fm_match else existing_content[:start_idx]
    )

    # Merge related_links into ## Conexoes Diretas
    conexoes_match = re.search(
        r"## Conexoes Diretas\r?\n([\s\S]*?)(?=\r?\n## |\r?\n<!-- |$)",
        body_and_links,
    )
    if conexoes_match:
        existing_direct_links = re.findall(
            r"- \[\[([^\]|]+)(?:\|[^\]]+)?\]\]", conexoes_match.group(1)
        )
        merged_direct_links = list(existing_direct_links)
        for link in zettel.related_links:
            if link not in merged_direct_links:
                merged_direct_links.append(link)
        new_conexoes_block = "## Conexoes Diretas\n" + "\n".join(
            f"- [[{link_slug}]]" for link_slug in merged_direct_links
        )
        body_and_links = (
            body_and_links[: conexoes_match.start()]
            + new_conexoes_block
            + body_and_links[conexoes_match.end() :]
        )
    elif zettel.related_links:
        ref_idx = body_and_links.find("## Referencias no Curso")
        new_conexoes_block = (
            "## Conexoes Diretas\n"
            + "\n".join(f"- [[{link_slug}]]" for link_slug in zettel.related_links)
            + "\n\n"
        )
        if ref_idx != -1:
            body_and_links = (
                body_and_links[:ref_idx] + new_conexoes_block + body_and_links[ref_idx:]
            )
        else:
            body_and_links = body_and_links.rstrip() + "\n\n" + new_conexoes_block

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
    force: bool = False,
) -> VaultExportResult:
    """Coordinates idempotent export of all lesson artifacts to the Obsidian Vault.

    Executes write_lesson_page, write_discipline_index, write_atomic_zettel for all
    extracted concepts, write_audit_report, and writes dialectical tensions when present.

    Args:
        vault_root: Target Obsidian Vault root directory.
        output: Validated WikiLessonOutput to persist.
        syllabus: Anchoring SyllabusModule for discipline metadata.
        force: Whether to auto-recover damaged or missing HTML delimiters.

    Returns:
        VaultExportResult consolidating paths of all exported files.

    Raises:
        ValueError: If file delimiters are damaged or missing during updates and force=False.
        OSError: If filesystem operations fail.
    """
    lesson_path = write_lesson_page(vault_root=vault_root, output=output, force=force)
    index_path = write_discipline_index(
        vault_root=vault_root, syllabus=syllabus, output=output, force=force
    )

    zettel_paths: list[Path] = []
    for zettel in output.extracted_zettels:
        z_path = write_atomic_zettel(
            vault_root=vault_root, zettel=zettel, output=output, force=force
        )
        zettel_paths.append(z_path)

    audit_path = write_audit_report(vault_root=vault_root, output=output)

    tension_paths: list[Path] = []
    tensions_index_path: Path | None = None
    if output.detected_tensions:
        for tension in output.detected_tensions:
            t_path = write_dialectical_tension(
                vault_root=vault_root,
                tension=tension,
                output=output,
                force=force,
            )
            tension_paths.append(t_path)
        tensions_index_path = write_tensions_index(
            vault_root=vault_root,
            tensions=output.detected_tensions,
            force=force,
        )

    return VaultExportResult(
        lesson_path=lesson_path,
        index_path=index_path,
        zettel_paths=zettel_paths,
        audit_report_path=audit_path,
        tension_paths=tension_paths,
        tensions_index_path=tensions_index_path,
    )


def write_dialectical_tension(
    vault_root: Path,
    tension: DialecticalTension,
    output: WikiLessonOutput,
    force: bool = False,
) -> Path:
    """Creates or idempotently updates a dialectical tension note in 04_Diario_Tensoes.

    Preserves manual notes, updates related atomic concepts without duplication,
    and appends the current lesson to the evidence list.

    Args:
        vault_root: Root directory of the target Obsidian Vault.
        tension: DialecticalTension model containing poles, thesis, and synthesis.
        output: Processed WikiLessonOutput with current lesson details.
        force: Whether to auto-recover missing delimiters instead of raising ValueError.

    Returns:
        Path to the written or updated tension Markdown note.

    Raises:
        ValueError: If delimiters are damaged in an existing tension file and force=False.
        OSError: If directory creation or file writing fails.
    """
    tensions_dir = vault_root / "04_Diario_Tensoes"
    tensions_dir.mkdir(parents=True, exist_ok=True)
    tension_path = tensions_dir / f"{tension.slug}.md"

    lesson_link = f"[[Aula_{output.lesson_number:02d}_{output.lesson_slug}]]"
    evidence_line = (
        f"- {lesson_link} ({output.discipline_name}): Tensão observada em {output.lesson_title}."
    )

    if not tension_path.is_file():
        z_lines = "\n".join(f"- [[{z}]]" for z in sorted(tension.related_zettel_slugs))
        z_block = f"\n{z_lines}\n" if z_lines else "\n"
        ev_block = f"\n{evidence_line}\n"

        content = (
            "---\n"
            'type: "diario_tensao"\n'
            f'slug: "{escape_yaml_str(tension.slug)}"\n'
            f'title: "{escape_yaml_str(tension.title)}"\n'
            f'pole_a: "{escape_yaml_str(tension.pole_a_framework)}"\n'
            f'pole_b: "{escape_yaml_str(tension.pole_b_framework)}"\n'
            "tags:\n"
            "  - mba/tensao\n"
            "  - mba/dilema-executivo\n"
            "---\n\n"
            f"# {tension.title}\n\n"
            "> [!abstract] Natureza do Trade-off\n"
            f"> {tension.tension_nature}\n\n"
            "## Polaridades Dialéticas\n\n"
            "| Dimensão | Polo A (Tese) | Polo B (Antítese) |\n"
            "| :--- | :--- | :--- |\n"
            f"| **Disciplina** | {tension.pole_a_discipline} | {tension.pole_b_discipline} |\n"
            f"| **Modelo/Framework** | {tension.pole_a_framework} | {tension.pole_b_framework} |\n"
            f"| **Proposição Central** | {tension.pole_a_thesis} | {tension.pole_b_thesis} |\n\n"
            "## Diretrizes de Síntese e Arbitragem Gerencial\n"
            f"{tension.synthesis_guidelines}\n\n"
            "## Conceitos Atômicos Relacionados\n"
            f"{AUTO_ZETTELS_START}{z_block}{AUTO_ZETTELS_END}\n\n"
            "## Aulas e Evidências Concorrentes\n"
            f"{AUTO_EVIDENCES_START}{ev_block}{AUTO_EVIDENCES_END}\n\n"
            "---\n"
            "## Anotações Pessoais e Resoluções Práticas\n"
            "<!-- Espaço preservado em reprocessamentos -->\n"
        )
        tension_path.write_text(content, encoding="utf-8")
        return tension_path

    existing_content = tension_path.read_text(encoding="utf-8")

    z_start = existing_content.find(AUTO_ZETTELS_START)
    z_end = existing_content.find(AUTO_ZETTELS_END)
    ev_start = existing_content.find(AUTO_EVIDENCES_START)
    ev_end = existing_content.find(AUTO_EVIDENCES_END)

    if -1 in (z_start, z_end, ev_start, ev_end):
        if not force:
            raise ValueError(f"Delimiters missing or damaged in tension note: {tension_path}")
        notes_marker = "## Anotações Pessoais e Resoluções Práticas"
        marker_idx = existing_content.find(notes_marker)
        preserved_notes = (
            existing_content[marker_idx:]
            if marker_idx != -1
            else f"---\n{notes_marker}\n<!-- Espaço preservado em reprocessamentos -->\n"
        )
        z_lines = "\n".join(f"- [[{z}]]" for z in sorted(tension.related_zettel_slugs))
        z_block = f"\n{z_lines}\n" if z_lines else "\n"
        ev_block = f"\n{evidence_line}\n"
        healed_content = (
            "---\n"
            'type: "diario_tensao"\n'
            f'slug: "{escape_yaml_str(tension.slug)}"\n'
            f'title: "{escape_yaml_str(tension.title)}"\n'
            f'pole_a: "{escape_yaml_str(tension.pole_a_framework)}"\n'
            f'pole_b: "{escape_yaml_str(tension.pole_b_framework)}"\n'
            "tags:\n"
            "  - mba/tensao\n"
            "  - mba/dilema-executivo\n"
            "---\n\n"
            f"# {tension.title}\n\n"
            "> [!abstract] Natureza do Trade-off\n"
            f"> {tension.tension_nature}\n\n"
            "## Polaridades Dialéticas\n\n"
            "| Dimensão | Polo A (Tese) | Polo B (Antítese) |\n"
            "| :--- | :--- | :--- |\n"
            f"| **Disciplina** | {tension.pole_a_discipline} | {tension.pole_b_discipline} |\n"
            f"| **Modelo/Framework** | {tension.pole_a_framework} | {tension.pole_b_framework} |\n"
            f"| **Proposição Central** | {tension.pole_a_thesis} | {tension.pole_b_thesis} |\n\n"
            "## Diretrizes de Síntese e Arbitragem Gerencial\n"
            f"{tension.synthesis_guidelines}\n\n"
            "## Conceitos Atômicos Relacionados\n"
            f"{AUTO_ZETTELS_START}{z_block}{AUTO_ZETTELS_END}\n\n"
            "## Aulas e Evidências Concorrentes\n"
            f"{AUTO_EVIDENCES_START}{ev_block}{AUTO_EVIDENCES_END}\n\n"
            f"{preserved_notes}"
        )
        tension_path.write_text(healed_content, encoding="utf-8")
        return tension_path

    # 1. Update related zettels block
    z_block_content = existing_content[z_start + len(AUTO_ZETTELS_START) : z_end]
    existing_zettels = re.findall(r"-\s*\[\[([^\]]+)\]\]", z_block_content)
    merged_zettels = list(dict.fromkeys(existing_zettels + tension.related_zettel_slugs))
    new_z_lines = "\n".join(f"- [[{z}]]" for z in merged_zettels)
    new_z_block = f"\n{new_z_lines}\n" if new_z_lines else "\n"

    # 2. Update evidences block
    ev_block_content = existing_content[ev_start + len(AUTO_EVIDENCES_START) : ev_end]
    existing_evidences = [
        line.strip() for line in ev_block_content.strip().splitlines() if line.strip()
    ]

    if not any(lesson_link in line for line in existing_evidences):
        existing_evidences.append(evidence_line)

    new_ev_lines = "\n".join(existing_evidences)
    new_ev_block = f"\n{new_ev_lines}\n" if new_ev_lines else "\n"

    part1 = existing_content[:z_start]
    part2 = existing_content[z_end + len(AUTO_ZETTELS_END) : ev_start]
    part3 = existing_content[ev_end + len(AUTO_EVIDENCES_END) :]

    updated_content = (
        f"{part1}{AUTO_ZETTELS_START}{new_z_block}{AUTO_ZETTELS_END}"
        f"{part2}{AUTO_EVIDENCES_START}{new_ev_block}{AUTO_EVIDENCES_END}"
        f"{part3}"
    )
    tension_path.write_text(updated_content, encoding="utf-8")
    return tension_path


def write_tensions_index(
    vault_root: Path,
    tensions: list[DialecticalTension],
    force: bool = False,
) -> Path:
    """Creates or idempotently updates the master index of dialectical tensions.

    Args:
        vault_root: Root directory of the target Obsidian Vault.
        tensions: List of DialecticalTension instances to index.
        force: Whether to auto-recover missing delimiters instead of raising ValueError.

    Returns:
        Path to the written or updated _Indice_Tensoes.md file.

    Raises:
        ValueError: If delimiters are damaged in an existing tensions index file and force=False.
        OSError: If directory creation or file writing fails.
    """
    tensions_dir = vault_root / "04_Diario_Tensoes"
    tensions_dir.mkdir(parents=True, exist_ok=True)
    index_path = tensions_dir / "_Indice_Tensoes.md"

    def format_entry(t: DialecticalTension) -> str:
        return (
            f"- [[{t.slug}|{t.title}]] "
            f"(`{t.pole_a_discipline}` vs `{t.pole_b_discipline}`): {t.tension_nature}"
        )

    if not index_path.is_file():
        entries = "\n".join(format_entry(t) for t in sorted(tensions, key=lambda x: x.slug))
        block = f"\n{entries}\n" if entries else "\n"
        content = (
            "---\n"
            'type: "moc_tensoes"\n'
            'title: "Índice de Tensões Dialéticas e Dilemas Executivos"\n'
            "tags:\n"
            "  - mba/indice\n"
            "  - mba/tensoes\n"
            "---\n\n"
            "# Diário de Tensões Dialéticas do MBA\n\n"
            "> [!quote] Visão Sistêmica\n"
            "> Mapeamento de trade-offs, polaridades teóricas e conflitos de modelos "
            "entre disciplinas do MBA.\n\n"
            "## Matriz de Tensões Mapeadas\n"
            f"{AUTO_TENSIONS_START}{block}{AUTO_TENSIONS_END}\n\n"
            "---\n"
            "## Notas de Síntese Pessoal\n"
            "<!-- Espaço preservado em reprocessamentos -->\n"
        )
        index_path.write_text(content, encoding="utf-8")
        return index_path

    existing_content = index_path.read_text(encoding="utf-8")
    start_idx = existing_content.find(AUTO_TENSIONS_START)
    end_idx = existing_content.find(AUTO_TENSIONS_END)

    if start_idx == -1 or end_idx == -1:
        if not force:
            raise ValueError(f"Delimiters missing or damaged in tensions index: {index_path}")
        notes_marker = "## Notas de Síntese Pessoal"
        marker_idx = existing_content.find(notes_marker)
        preserved_notes = (
            existing_content[marker_idx:]
            if marker_idx != -1
            else f"---\n{notes_marker}\n<!-- Espaço preservado em reprocessamentos -->\n"
        )
        entries = "\n".join(format_entry(t) for t in sorted(tensions, key=lambda x: x.slug))
        block = f"\n{entries}\n" if entries else "\n"
        healed_content = (
            "---\n"
            'type: "moc_tensoes"\n'
            'title: "Índice de Tensões Dialéticas e Dilemas Executivos"\n'
            "tags:\n"
            "  - mba/indice\n"
            "  - mba/tensoes\n"
            "---\n\n"
            "# Diário de Tensões Dialéticas do MBA\n\n"
            "> [!quote] Visão Sistêmica\n"
            "> Mapeamento de trade-offs, polaridades teóricas e conflitos de modelos "
            "entre disciplinas do MBA.\n\n"
            "## Matriz de Tensões Mapeadas\n"
            f"{AUTO_TENSIONS_START}{block}{AUTO_TENSIONS_END}\n\n"
            f"{preserved_notes}"
        )
        index_path.write_text(healed_content, encoding="utf-8")
        return index_path

    block_content = existing_content[start_idx + len(AUTO_TENSIONS_START) : end_idx]
    existing_lines = [line.strip() for line in block_content.strip().splitlines() if line.strip()]

    existing_slugs: set[str] = set()
    for line in existing_lines:
        match = re.search(r"\[\[([^|\]]+)", line)
        if match:
            existing_slugs.add(match.group(1))

    new_lines = list(existing_lines)
    for t in sorted(tensions, key=lambda x: x.slug):
        if t.slug not in existing_slugs:
            new_lines.append(format_entry(t))
            existing_slugs.add(t.slug)

    new_lines.sort()
    new_block = "\n" + "\n".join(new_lines) + "\n" if new_lines else "\n"

    part1 = existing_content[:start_idx]
    part2 = existing_content[end_idx + len(AUTO_TENSIONS_END) :]
    updated_content = f"{part1}{AUTO_TENSIONS_START}{new_block}{AUTO_TENSIONS_END}{part2}"
    index_path.write_text(updated_content, encoding="utf-8")
    return index_path


__all__ = [
    "AUTO_BACKLINKS_END",
    "AUTO_BACKLINKS_START",
    "AUTO_CONTENT_END",
    "AUTO_CONTENT_START",
    "AUTO_EVIDENCES_END",
    "AUTO_EVIDENCES_START",
    "AUTO_LESSONS_END",
    "AUTO_LESSONS_START",
    "AUTO_TENSIONS_END",
    "AUTO_TENSIONS_START",
    "AUTO_ZETTELS_END",
    "AUTO_ZETTELS_START",
    "VaultExportResult",
    "export_lesson_to_vault",
    "format_zettels_section",
    "write_atomic_zettel",
    "write_audit_report",
    "write_dialectical_tension",
    "write_discipline_index",
    "write_lesson_page",
    "write_tensions_index",
]

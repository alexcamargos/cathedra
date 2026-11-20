"""Idempotent Obsidian Vault exporter module.

Persists and updates lesson wiki pages, discipline indices (MOCs), atomic Zettelkasten
notes, and factual audit JSON reports while preserving manual human notes and preventing
link duplication across re-runs.
"""

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from cathedra.schemas import (
    AtomicZettel,
    DialecticalTension,
    LessonAuditReport,
    LessonPipelineState,
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


def _ensure_managed_block(
    content: str, start: str, end: str, path: Path, force: bool, initial: str
) -> str:
    """Validate delimiters or append a new block without deleting existing text."""
    start_count = content.count(start)
    end_count = content.count(end)
    if (
        start_count > 1
        or end_count > 1
        or (start_count == end_count == 1 and content.find(start) > content.find(end))
    ):
        raise ValueError(f"Delimiters are duplicated or out of order in {path}")
    if start_count == end_count == 1:
        return content
    if not force:
        raise ValueError(f"Delimiters '{start}' and '{end}' not found in {path}")
    preserved = content.replace(start, "", 1).replace(end, "", 1)
    return f"{preserved}\n\n{start}\n{initial}\n{end}\n"


def _write_text_atomically(path: Path, content: str) -> None:
    """Replace a single file only after its complete contents have been written."""
    if path.is_symlink():
        raise ValueError(f"Symlink is not supported in vault export: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        if path.exists():
            shutil.copymode(path, temporary_path)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


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
        _write_text_atomically(index_path, content)
        return index_path

    existing_content = index_path.read_text(encoding="utf-8")
    existing_content = _ensure_managed_block(
        existing_content, AUTO_LESSONS_START, AUTO_LESSONS_END, index_path, force, lesson_entry
    )
    start_idx = existing_content.index(AUTO_LESSONS_START)
    end_idx = existing_content.index(AUTO_LESSONS_END)

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
    _write_text_atomically(index_path, updated_content)
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


def format_pending_review_callout(output: WikiLessonOutput) -> str:
    """Formats an Obsidian warning callout when a lesson has pending factual review items."""
    if not output.has_pending_review:
        return ""
    pending_items = [
        item
        for item in output.audit_items
        if item.evidence_status == "pending_review" or item.verdict != "verified"
    ]
    lines = [
        "> [!warning] Revisão Factual Pendente",
        "> Esta aula foi exportada com pendências de verificação literal na fonte. "
        "Consulte o relatório em `03_Auditoria_Factual/`.",
    ]
    for item in pending_items[:5]:
        snippet = " ".join(item.quote.split())
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        lines.append(f"> - `{item.claim_id}` ({item.verdict}): {snippet}")
    return "\n".join(lines)


def write_lesson_page(
    vault_root: Path,
    output: WikiLessonOutput,
    force: bool = False,
) -> Path:
    """Writes or idempotently updates a lesson wiki page (Aula_NN_slug.md).

    Replaces content strictly within AUTO-CONTENT delimiters. On forced recovery,
    preserves the existing text and appends a new generated block.

    Args:
        vault_root: Target Obsidian Vault root directory.
        output: Completed WikiLessonOutput containing validated lesson data.
        force: Whether to auto-recover missing delimiters instead of raising ValueError.

    Returns:
        Path to the saved or updated lesson Markdown file.

    Raises:
        ValueError: If delimiters are ambiguous, or missing without force.
    """
    discipline_dir = vault_root / "01_Wiki_Disciplinas" / output.discipline_slug
    discipline_dir.mkdir(parents=True, exist_ok=True)
    filename = f"Aula_{output.lesson_number:02d}_{output.lesson_slug}.md"
    lesson_path = discipline_dir / filename

    zettel_block = format_zettels_section(output.extracted_zettels)
    pending_callout = format_pending_review_callout(output)
    auto_body = output.body_markdown.strip()
    if pending_callout:
        auto_body = f"{pending_callout}\n\n{auto_body}"
    if zettel_block:
        auto_body = f"{auto_body}\n\n{zettel_block}"

    fact_check_status = "pending_review" if output.has_pending_review else "verified"

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
            f"fact_check_status: {fact_check_status}\n"
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
        _write_text_atomically(lesson_path, content)
        return lesson_path

    existing_content = lesson_path.read_text(encoding="utf-8")
    start_count = existing_content.count(AUTO_CONTENT_START)
    end_count = existing_content.count(AUTO_CONTENT_END)
    start_idx = existing_content.find(AUTO_CONTENT_START)
    end_idx = existing_content.find(AUTO_CONTENT_END)

    if start_count > 1 or end_count > 1 or (start_count == end_count == 1 and start_idx > end_idx):
        raise ValueError(f"Delimiters are duplicated or out of order in {lesson_path}")

    if start_count == 0 or end_count == 0:
        if not force:
            raise ValueError(
                f"Delimiters '{AUTO_CONTENT_START}' and '{AUTO_CONTENT_END}' "
                f"not found in {lesson_path}"
            )
        preserved = existing_content.replace(AUTO_CONTENT_START, "", 1)
        preserved = preserved.replace(AUTO_CONTENT_END, "", 1)
        updated_content = f"{preserved}\n\n{AUTO_CONTENT_START}\n{auto_body}\n{AUTO_CONTENT_END}\n"
        _write_text_atomically(lesson_path, updated_content)
        return lesson_path

    before_block = existing_content[: start_idx + len(AUTO_CONTENT_START)]
    after_block = existing_content[end_idx:]
    updated_content = f"{before_block}\n{auto_body}\n{after_block}"
    _write_text_atomically(lesson_path, updated_content)
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
        _write_text_atomically(zettel_path, content)
        return zettel_path

    existing_content = zettel_path.read_text(encoding="utf-8")
    existing_content = _ensure_managed_block(
        existing_content,
        AUTO_BACKLINKS_START,
        AUTO_BACKLINKS_END,
        zettel_path,
        force,
        lesson_backlink,
    )
    start_idx = existing_content.index(AUTO_BACKLINKS_START)
    end_idx = existing_content.index(AUTO_BACKLINKS_END)

    # 1. Merge domain tags into frontmatter without duplicates
    fm_match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", existing_content, re.DOTALL)
    body_and_links = existing_content[:start_idx]
    if fm_match:
        fm_text = fm_match.group(1)
        tags_section = re.search(r"(?m)^tags:[ \t]*\n((?:[ \t]+-[ \t]+[^\n]+\n?)*)", fm_text)
        if tags_section:
            existing_tags = {
                line.strip().lstrip("-").strip() for line in tags_section.group(1).splitlines()
            }
            missing_tags = [tag for tag in zettel.domain_tags if tag not in existing_tags]
            if missing_tags:
                insert_at = fm_match.start(1) + tags_section.end(1)
                prefix = "" if body_and_links[:insert_at].endswith("\n") else "\n"
                addition = prefix + "".join(f"  - {tag}\n" for tag in missing_tags)
                body_and_links = body_and_links[:insert_at] + addition + body_and_links[insert_at:]

    # Merge related_links into ## Conexoes Diretas
    conexoes_match = re.search(
        r"## Conexoes Diretas\r?\n([\s\S]*?)(?=\r?\n## |\r?\n<!-- |$)",
        body_and_links,
    )
    if conexoes_match:
        existing_direct_links = re.findall(
            r"- \[\[([^\]|]+)(?:\|[^\]]+)?\]\]", conexoes_match.group(1)
        )
        new_links = [link for link in zettel.related_links if link not in existing_direct_links]
        if new_links:
            insertion = "\n" + "\n".join(f"- [[{link}]]" for link in new_links)
            body_and_links = (
                body_and_links[: conexoes_match.end()]
                + insertion
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

    updated_content = f"{body_and_links}{AUTO_BACKLINKS_START}{new_backlinks_content}{after_block}"
    _write_text_atomically(zettel_path, updated_content)
    return zettel_path


def write_blocked_audit_report(vault_root: Path, state: LessonPipelineState) -> Path:
    """Persist a blocked audit separately without replacing a published audit."""
    if state.fact_check_passed:
        raise ValueError("A auditoria factual aprovada não é uma auditoria pendente.")
    report = LessonAuditReport(
        discipline_slug=state.discipline_slug,
        discipline_name=state.discipline_name,
        lesson_number=state.lesson_number,
        lesson_title=state.lesson_title,
        processed_date=date.today(),
        fact_check_passed=False,
        total_claims_audited=len(state.audit_items),
        removed_unsupported_claims=state.removed_unsupported_claims,
        audit_items=state.audit_items,
        source_transcript_filename=state.transcript.source_filename if state.transcript else None,
        source_transcript_path=state.source_transcript_path,
        source_transcript_binding=state.source_transcript_binding,
    )
    directory = vault_root / "03_Auditoria_Factual" / "pendentes"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{state.discipline_slug}_Aula_{state.lesson_number:02d}_audit.json"
    _write_text_atomically(path, report.model_dump_json(indent=2))
    return path


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
        source_transcript_filename=output.source_transcript_filename,
        source_transcript_path=output.source_transcript_path,
        source_transcript_binding=output.source_transcript_binding,
    )

    _write_text_atomically(report_path, report.model_dump_json(indent=2))
    return report_path


def _write_lesson_artifacts(
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
    if not output.fact_check_passed:
        raise ValueError("Não é possível exportar uma aula reprovada na auditoria factual.")

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


def _artifact_paths(output: WikiLessonOutput, syllabus: SyllabusModule) -> list[Path]:
    """Compute the complete set of relative paths touched by an export."""
    slugs = [output.discipline_slug, syllabus.discipline_slug, output.lesson_slug]
    slugs.extend(zettel.slug for zettel in output.extracted_zettels)
    slugs.extend(tension.slug for tension in output.detected_tensions)
    if any(not slug or slug in {".", ".."} or any(c in slug for c in "/\\:") for slug in slugs):
        raise ValueError("Invalid slug in vault export")
    if output.discipline_slug != syllabus.discipline_slug:
        raise ValueError("Discipline mismatch in vault export")
    if any(tension.slug.casefold() == "_indice_tensoes" for tension in output.detected_tensions):
        raise ValueError("Tension slug conflicts with index")
    discipline = Path("01_Wiki_Disciplinas") / output.discipline_slug
    paths = [
        discipline / f"Aula_{output.lesson_number:02d}_{output.lesson_slug}.md",
        discipline / "_Indice_Materia.md",
        *(Path("02_Zettelkasten") / f"{z.slug}.md" for z in output.extracted_zettels),
        Path("03_Auditoria_Factual")
        / f"{output.discipline_slug}_Aula_{output.lesson_number:02d}_audit.json",
        *(Path("04_Diario_Tensoes") / f"{t.slug}.md" for t in output.detected_tensions),
    ]
    if output.detected_tensions:
        paths.append(Path("04_Diario_Tensoes") / "_Indice_Tensoes.md")
    return list(dict.fromkeys(paths))


def _check_safe_target(vault_root: Path, relative: Path) -> Path:
    """Reject symlinks and paths outside the vault before reading or replacing files."""
    target = vault_root / relative
    if not target.resolve().is_relative_to(vault_root.resolve()):
        raise ValueError(f"Vault path escapes root: {target}")
    current = vault_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Symlink is not supported in vault export: {current}")
    if target.exists() and not target.is_file():
        raise ValueError(f"Vault target is not a regular file: {target}")
    return target


def export_lesson_to_vault(
    vault_root: Path,
    output: WikiLessonOutput,
    syllabus: SyllabusModule,
    force: bool = False,
) -> VaultExportResult:
    """Prepare all files separately, then replace them with rollback on errors."""
    if not output.fact_check_passed:
        raise ValueError("Não é possível exportar uma aula reprovada na auditoria factual.")
    paths = _artifact_paths(output, syllabus)
    vault_root.mkdir(parents=True, exist_ok=True)
    for relative in paths:
        _check_safe_target(vault_root, relative)

    staging_dir = Path(tempfile.mkdtemp(prefix=".cathedra-export-", dir=vault_root.parent))
    keep_staging = False
    try:
        staging_root = staging_dir / "vault"
        snapshots: dict[Path, bytes | None] = {}
        for relative in paths:
            target = _check_safe_target(vault_root, relative)
            snapshot = target.read_bytes() if target.exists() else None
            snapshots[relative] = snapshot
            if snapshot is not None:
                staged = staging_root / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(snapshot)
                shutil.copystat(target, staged)
                backup = staging_dir / "backup" / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(snapshot)
                shutil.copystat(staged, backup)

        result = _write_lesson_artifacts(staging_root, output, syllabus, force=force)
        installed: dict[Path, bytes] = {}
        try:
            for relative in paths:
                target = _check_safe_target(vault_root, relative)
                current = target.read_bytes() if target.exists() else None
                if current != snapshots[relative]:
                    raise RuntimeError(f"Vault file changed during export: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                staged = staging_root / relative
                installed_content = staged.read_bytes()
                os.replace(staged, target)
                installed[relative] = installed_content
        except Exception as exc:
            rollback_errors: list[str] = []
            for relative in reversed(installed):
                target = vault_root / relative
                try:
                    target = _check_safe_target(vault_root, relative)
                    current = target.read_bytes() if target.exists() else None
                    if current != installed[relative]:
                        rollback_errors.append(f"{target}: changed after installation")
                        continue
                    if snapshots[relative] is None:
                        target.unlink()
                    else:
                        os.replace(staging_dir / "backup" / relative, target)
                except (OSError, ValueError) as rollback_exc:
                    rollback_errors.append(f"{target}: {rollback_exc}")
            if rollback_errors:
                keep_staging = True
                raise RuntimeError(
                    f"Vault rollback failed; backups retained in {staging_dir}: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise

        def destination(staged_path: Path) -> Path:
            return vault_root / staged_path.relative_to(staging_root)

        return VaultExportResult(
            lesson_path=destination(result.lesson_path),
            index_path=destination(result.index_path),
            zettel_paths=[destination(path) for path in result.zettel_paths],
            audit_report_path=destination(result.audit_report_path),
            tension_paths=[destination(path) for path in result.tension_paths],
            tensions_index_path=(
                destination(result.tensions_index_path) if result.tensions_index_path else None
            ),
        )
    finally:
        if not keep_staging:
            shutil.rmtree(staging_dir)


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
        _write_text_atomically(tension_path, content)
        return tension_path

    existing_content = tension_path.read_text(encoding="utf-8")
    z_lines = "\n".join(f"- [[{z}]]" for z in sorted(tension.related_zettel_slugs))
    existing_content = _ensure_managed_block(
        existing_content, AUTO_ZETTELS_START, AUTO_ZETTELS_END, tension_path, force, z_lines
    )
    existing_content = _ensure_managed_block(
        existing_content,
        AUTO_EVIDENCES_START,
        AUTO_EVIDENCES_END,
        tension_path,
        force,
        evidence_line,
    )
    z_start = existing_content.index(AUTO_ZETTELS_START)
    z_end = existing_content.index(AUTO_ZETTELS_END)
    ev_start = existing_content.index(AUTO_EVIDENCES_START)
    ev_end = existing_content.index(AUTO_EVIDENCES_END)
    if not (z_end < ev_start or ev_end < z_start):
        raise ValueError(f"Delimiters overlap in {tension_path}")

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

    updated_content = existing_content
    replacements = [
        (
            z_start,
            z_end + len(AUTO_ZETTELS_END),
            f"{AUTO_ZETTELS_START}{new_z_block}{AUTO_ZETTELS_END}",
        ),
        (
            ev_start,
            ev_end + len(AUTO_EVIDENCES_END),
            f"{AUTO_EVIDENCES_START}{new_ev_block}{AUTO_EVIDENCES_END}",
        ),
    ]
    for start, end, replacement in sorted(replacements, reverse=True):
        updated_content = updated_content[:start] + replacement + updated_content[end:]
    _write_text_atomically(tension_path, updated_content)
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
        _write_text_atomically(index_path, content)
        return index_path

    existing_content = index_path.read_text(encoding="utf-8")
    entries = "\n".join(format_entry(t) for t in sorted(tensions, key=lambda x: x.slug))
    existing_content = _ensure_managed_block(
        existing_content, AUTO_TENSIONS_START, AUTO_TENSIONS_END, index_path, force, entries
    )
    start_idx = existing_content.index(AUTO_TENSIONS_START)
    end_idx = existing_content.index(AUTO_TENSIONS_END)

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
    _write_text_atomically(index_path, updated_content)
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

"""Unit tests for the idempotent Obsidian exporter module (obsidian_writer.py).

Validates generation and idempotent updates for discipline indices (_Indice_Materia.md),
lesson wiki pages (Aula_NN_slug.md), Zettelkasten atomic notes, and factual audit JSON reports.
"""

import json
import os
from datetime import date
from pathlib import Path

import pytest

from cathedra.exporters.obsidian_writer import (
    VaultExportResult,
    export_lesson_to_vault,
    format_zettels_section,
    write_atomic_zettel,
    write_audit_report,
    write_dialectical_tension,
    write_discipline_index,
    write_lesson_page,
    write_tensions_index,
)
from cathedra.schemas import (
    AtomicZettel,
    ClaimAuditItem,
    DialecticalTension,
    LessonAuditReport,
    SyllabusModule,
    WikiLessonOutput,
)


@pytest.fixture
def sample_syllabus() -> SyllabusModule:
    """Fixture providing a standard SyllabusModule instance.

    Args:
        None.

    Returns:
        Populated SyllabusModule instance.

    Raises:
        None.
    """
    return SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        professor="Prof. Dr. Roberto Albuquerque",
        syllabus_summary="Análise de decisões de investimento e financiamento.",
        topics=["VPL", "TIR", "Custo de Capital"],
        bibliography=[
            "Brealey, Myers & Allen. Princípios de Finanças Corporativas.",
            "Damodaran, Aswath. Finanças Corporativas Aplicadas.",
        ],
    )


@pytest.fixture
def sample_lesson_output() -> WikiLessonOutput:
    """Fixture providing a sample WikiLessonOutput instance.

    Args:
        None.

    Returns:
        Populated WikiLessonOutput instance.

    Raises:
        None.
    """
    zettel = AtomicZettel(
        slug="valor-presente-liquido",
        title="Valor Presente Líquido (VPL)",
        domain_tags=["financas", "orcamento-capital"],
        content_markdown=(
            "O VPL representa a riqueza econômica gerada pelo projeto a valor presente."
        ),
        related_links=["taxa-interna-retorno", "taxa-minima-atratividade"],
    )
    claim = ClaimAuditItem(
        claim_id="CLM-001",
        quote="O VPL desconta fluxos futuros à taxa mínima de atratividade.",
        category="technical",
        verdict="verified",
        severity=None,
        evidence_source="Slide 12",
        proposed_fix=None,
    )
    return WikiLessonOutput(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        lesson_number=1,
        lesson_title="Critérios de Decisão de Investimento",
        lesson_slug="criterios-decisao",
        processed_date=date(2026, 10, 18),
        source_slide_filename="aula_01_financas.pdf",
        fact_check_passed=True,
        removed_unsupported_claims=0,
        body_markdown=(
            "# Critérios de Decisão de Investimento\n\n"
            "A análise de investimentos corporativos fundamenta-se no desconto dos fluxos de caixa."
        ),
        extracted_zettels=[zettel],
        audit_items=[claim],
    )


@pytest.fixture
def sample_tension() -> DialecticalTension:
    return DialecticalTension(
        slug="controle-vs-autonomia",
        title="Controle vs Autonomia",
        pole_a_discipline="financas",
        pole_a_framework="Controle",
        pole_a_thesis="Controlar.",
        pole_b_discipline="inovacao",
        pole_b_framework="Autonomia",
        pole_b_thesis="Delegar.",
        tension_nature="Controle vs velocidade",
        synthesis_guidelines="Conciliar.",
        related_zettel_slugs=["vpl"],
    )


def test_zettel_update_preserves_custom_frontmatter_and_direct_link_notes(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    zettel = sample_lesson_output.extracted_zettels[0]
    path = write_atomic_zettel(tmp_path, zettel, sample_lesson_output)
    original = path.read_text(encoding="utf-8")
    original = original.replace("tags:\n", "custom: meu valor\ntags:\n")
    original = original.replace("## Conexoes Diretas\n", "## Conexoes Diretas\nNota minha.\n")
    path.write_text(original, encoding="utf-8")
    update = zettel.model_copy(update={"domain_tags": ["nova-tag"], "related_links": ["outro"]})

    write_atomic_zettel(tmp_path, update, sample_lesson_output)
    updated = path.read_text(encoding="utf-8")
    assert "custom: meu valor" in updated
    assert "Nota minha." in updated
    assert "nova-tag" in updated
    assert "[[outro]]" in updated


def _write_sample_vault_file(
    kind: str,
    root: Path,
    syllabus: SyllabusModule,
    output: WikiLessonOutput,
    tension: DialecticalTension,
) -> Path:
    if kind == "index":
        return write_discipline_index(root, syllabus, output, force=True)
    if kind == "zettel":
        return write_atomic_zettel(root, output.extracted_zettels[0], output, force=True)
    if kind == "tension":
        return write_dialectical_tension(root, tension, output, force=True)
    return write_tensions_index(root, [tension], force=True)


@pytest.mark.parametrize("kind", ["index", "zettel", "tension", "tensions_index"])
def test_force_recovery_preserves_other_vault_files(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
    sample_tension: DialecticalTension,
    kind: str,
) -> None:
    """Missing markers must not delete content; repeating recovery is idempotent."""

    def writer() -> Path:
        return _write_sample_vault_file(
            kind, tmp_path, sample_syllabus, sample_lesson_output, sample_tension
        )

    path = writer()
    original = (
        "# Nota existente\n\nTexto anterior insubstituível.\n\n"
        "## Referencias no Curso\nObservação pessoal.\n"
    )
    path.write_text(original, encoding="utf-8")

    writer()
    healed = path.read_text(encoding="utf-8")
    remaining = iter(healed)
    assert all(any(char == expected for char in remaining) for expected in original)
    writer()
    assert path.read_text(encoding="utf-8") == healed


@pytest.mark.parametrize("kind", ["index", "zettel", "tension", "tensions_index"])
@pytest.mark.parametrize("mode", ["inverted", "duplicated"])
def test_other_vault_files_reject_inverted_markers_without_writes(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
    sample_tension: DialecticalTension,
    kind: str,
    mode: str,
) -> None:
    def writer() -> Path:
        return _write_sample_vault_file(
            kind, tmp_path, sample_syllabus, sample_lesson_output, sample_tension
        )

    markers = {
        "index": "<!-- AUTO-LESSONS:END -->\n<!-- AUTO-LESSONS:START -->",
        "zettel": "<!-- AUTO-BACKLINKS:END -->\n<!-- AUTO-BACKLINKS:START -->",
        "tension": "<!-- AUTO-ZETTELS:END -->\n<!-- AUTO-ZETTELS:START -->",
        "tensions_index": "<!-- AUTO-TENSIONS:END -->\n<!-- AUTO-TENSIONS:START -->",
    }[kind]
    if mode == "duplicated":
        markers = markers.replace(":END -->", ":START -->")
    path = writer()
    original = f"Nota do usuário.\n{markers}\nOutra nota.\n"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="[Dd]elimit"):
        writer()
    assert path.read_text(encoding="utf-8") == original


def test_tension_rejects_overlapping_blocks(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
    sample_tension: DialecticalTension,
) -> None:
    path = write_dialectical_tension(tmp_path, sample_tension, sample_lesson_output)
    original = (
        "Nota do usuário.\n<!-- AUTO-ZETTELS:START -->\n<!-- AUTO-EVIDENCES:START -->\n"
        "<!-- AUTO-ZETTELS:END -->\n<!-- AUTO-EVIDENCES:END -->\n"
    )
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="[Dd]elimit"):
        write_dialectical_tension(tmp_path, sample_tension, sample_lesson_output, force=True)
    assert path.read_text(encoding="utf-8") == original


def test_export_staging_failure_leaves_existing_vault_unchanged(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure generating a later artifact must not publish an earlier one."""
    initial = export_lesson_to_vault(tmp_path, sample_lesson_output, sample_syllabus)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    changed = sample_lesson_output.model_copy(update={"body_markdown": "Corpo novo."})

    def fail_audit(*args: object, **kwargs: object) -> Path:
        raise OSError("Falha simulada ao preparar auditoria")

    monkeypatch.setattr("cathedra.exporters.obsidian_writer.write_audit_report", fail_audit)
    with pytest.raises(OSError, match="Falha simulada"):
        export_lesson_to_vault(tmp_path, changed, sample_syllabus)
    assert initial.lesson_path.read_bytes() == before[initial.lesson_path]
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_export_aborts_if_user_edits_file_during_preparation(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An edit made during staging must not be replaced by the pending export."""
    initial = export_lesson_to_vault(tmp_path, sample_lesson_output, sample_syllabus)
    original_writer = write_audit_report

    def edit_during_audit(vault_root: Path, output: WikiLessonOutput) -> Path:
        result = original_writer(vault_root, output)
        initial.lesson_path.write_text("Alteração do usuário", encoding="utf-8")
        return result

    monkeypatch.setattr("cathedra.exporters.obsidian_writer.write_audit_report", edit_during_audit)
    changed = sample_lesson_output.model_copy(update={"body_markdown": "Corpo novo."})
    with pytest.raises(RuntimeError, match="changed during export"):
        export_lesson_to_vault(tmp_path, changed, sample_syllabus)
    assert initial.lesson_path.read_text(encoding="utf-8") == "Alteração do usuário"


def test_export_commit_failure_restores_previous_files(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed replacement rolls back files already installed in the vault."""
    export_lesson_to_vault(tmp_path, sample_lesson_output, sample_syllabus)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    changed = sample_lesson_output.model_copy(update={"body_markdown": "Corpo novo."})
    original_replace = os.replace
    calls = 0

    def fail_second_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        nonlocal calls
        if Path(dst).resolve().is_relative_to(tmp_path.resolve()):
            calls += 1
            if calls == 2:
                raise OSError("Falha simulada na substituição")
        original_replace(src, dst)

    monkeypatch.setattr("cathedra.exporters.obsidian_writer.os.replace", fail_second_replace)
    with pytest.raises(OSError, match="Falha simulada"):
        export_lesson_to_vault(tmp_path, changed, sample_syllabus)
    assert calls >= 2
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_export_rollback_does_not_overwrite_concurrent_edit(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback must preserve a user's edit made after a file was installed."""
    result = export_lesson_to_vault(tmp_path, sample_lesson_output, sample_syllabus)
    changed = sample_lesson_output.model_copy(update={"body_markdown": "Corpo novo."})
    original_replace = os.replace
    calls = 0

    def fail_after_concurrent_edit(
        src: str | os.PathLike[str], dst: str | os.PathLike[str]
    ) -> None:
        nonlocal calls
        if Path(dst).resolve().is_relative_to(tmp_path.resolve()):
            calls += 1
            if calls == 2:
                result.lesson_path.write_text("Edição simultânea do usuário", encoding="utf-8")
                raise OSError("Falha simulada")
        original_replace(src, dst)

    monkeypatch.setattr("cathedra.exporters.obsidian_writer.os.replace", fail_after_concurrent_edit)
    with pytest.raises(RuntimeError, match="backups retained"):
        export_lesson_to_vault(tmp_path, changed, sample_syllabus)
    assert result.lesson_path.read_text(encoding="utf-8") == "Edição simultânea do usuário"


def test_export_rejects_slug_with_path_traversal(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    bad_zettel = sample_lesson_output.extracted_zettels[0].model_copy(update={"slug": "../fora"})
    output = sample_lesson_output.model_copy(update={"extracted_zettels": [bad_zettel]})
    with pytest.raises(ValueError, match="slug"):
        export_lesson_to_vault(tmp_path, output, sample_syllabus)
    assert list(tmp_path.iterdir()) == []


def test_single_tensions_index_write_is_atomic_on_failure(
    tmp_path: Path,
    sample_tension: DialecticalTension,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_tensions_index(tmp_path, [sample_tension])
    before = path.read_bytes()
    other = sample_tension.model_copy(update={"slug": "outro", "title": "Outro"})

    def fail_replace(src: object, dst: object) -> None:
        raise OSError("Falha simulada na escrita")

    monkeypatch.setattr("cathedra.exporters.obsidian_writer.os.replace", fail_replace)
    with pytest.raises(OSError, match="Falha simulada"):
        write_tensions_index(tmp_path, [sample_tension, other])
    assert path.read_bytes() == before
    assert sorted(path.parent.iterdir()) == [path]


def test_export_rejects_failed_audit_before_any_write(
    tmp_path: Path, sample_syllabus: SyllabusModule, sample_lesson_output: WikiLessonOutput
) -> None:
    """The exporter independently rejects unapproved lessons before mutating the vault."""
    sample_lesson_output.fact_check_passed = False

    with pytest.raises(ValueError, match="auditoria factual"):
        export_lesson_to_vault(tmp_path, sample_lesson_output, sample_syllabus, force=True)

    assert list(tmp_path.iterdir()) == []


def test_write_discipline_index_creates_new_file(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_discipline_index generates _Indice_Materia.md with correct templates.

    Args:
        tmp_path: Pytest temporary directory.
        sample_syllabus: Sample syllabus module fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    index_path = write_discipline_index(
        vault_root=tmp_path,
        syllabus=sample_syllabus,
        output=sample_lesson_output,
    )

    assert index_path.is_file()
    content = index_path.read_text(encoding="utf-8")
    assert "type: moc_disciplina" in content
    assert 'discipline_slug: "financas-corporativas"' in content
    assert 'discipline_name: "Finanças Corporativas"' in content
    assert "<!-- AUTO-LESSONS:START -->" in content
    assert "<!-- AUTO-LESSONS:END -->" in content
    expected_link = "- [[Aula_01_criterios-decisao|Aula 01: Critérios de Decisão de Investimento]]"
    assert expected_link in content
    assert "Brealey, Myers & Allen" in content


def test_write_discipline_index_idempotent_no_duplicates(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that re-running write_discipline_index does not duplicate links or overwrite notes.

    Args:
        tmp_path: Pytest temporary directory.
        sample_syllabus: Sample syllabus module fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    # 1. Initial write
    index_path = write_discipline_index(
        vault_root=tmp_path,
        syllabus=sample_syllabus,
        output=sample_lesson_output,
    )

    # 2. User appends manual notes outside of delimiters
    manual_note = "\n\n## Anotações do Aluno\n- Revisar cálculo de WACC antes da P1."
    index_path.write_text(index_path.read_text(encoding="utf-8") + manual_note, encoding="utf-8")

    # 3. Reprocess the same lesson
    updated_path = write_discipline_index(
        vault_root=tmp_path,
        syllabus=sample_syllabus,
        output=sample_lesson_output,
    )

    content = updated_path.read_text(encoding="utf-8")
    expected_link = "- [[Aula_01_criterios-decisao|Aula 01: Critérios de Decisão de Investimento]]"
    assert content.count(expected_link) == 1
    assert "## Anotações do Aluno" in content
    assert "Revisar cálculo de WACC antes da P1." in content


def test_write_discipline_index_orders_multiple_lessons(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that multiple lessons added to index are ordered numerically by lesson number.

    Args:
        tmp_path: Pytest temporary directory.
        sample_syllabus: Sample syllabus module fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    write_discipline_index(
        vault_root=tmp_path,
        syllabus=sample_syllabus,
        output=sample_lesson_output,
    )

    lesson_2 = sample_lesson_output.model_copy(
        update={
            "lesson_number": 2,
            "lesson_title": "Taxa Interna de Retorno",
            "lesson_slug": "taxa-interna-retorno",
        }
    )
    index_path = write_discipline_index(
        vault_root=tmp_path,
        syllabus=sample_syllabus,
        output=lesson_2,
    )

    content = index_path.read_text(encoding="utf-8")
    idx_1 = content.find("Aula_01_criterios-decisao")
    idx_2 = content.find("Aula_02_taxa-interna-retorno")
    assert idx_1 != -1 and idx_2 != -1
    assert idx_1 < idx_2


def test_write_lesson_page_creates_and_preserves_personal_notes(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_lesson_page creates lesson wiki page and preserves manual notes on rerun.

    Args:
        tmp_path: Pytest temporary directory.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    # 1. Create fresh lesson page
    lesson_path = write_lesson_page(vault_root=tmp_path, output=sample_lesson_output)
    assert lesson_path.is_file()
    assert lesson_path.name == "Aula_01_criterios-decisao.md"

    content = lesson_path.read_text(encoding="utf-8")
    assert "type: wiki_aula" in content
    assert "<!-- AUTO-CONTENT:START -->" in content
    assert "<!-- AUTO-CONTENT:END -->" in content
    assert "- [[valor-presente-liquido|Valor Presente Líquido (VPL)]]" in content
    assert "## Notas Pessoais de Aula" in content

    # 2. Add manual notes in personal section
    manual_content = content + "\n- Anotação pessoal do aluno feita em sala.\n"
    lesson_path.write_text(manual_content, encoding="utf-8")

    # 3. Update lesson with new body and reprocess
    updated_output = sample_lesson_output.model_copy(
        update={
            "body_markdown": "# Texto Atualizado e Expandido\nNovo parágrafo didático.",
            "removed_unsupported_claims": 2,
        }
    )
    reprocessed_path = write_lesson_page(vault_root=tmp_path, output=updated_output)
    reprocessed_content = reprocessed_path.read_text(encoding="utf-8")

    assert "# Texto Atualizado e Expandido" in reprocessed_content
    # Machine-managed audit frontmatter updates selectively while preserving manual notes.
    assert "removed_claims: 2" in reprocessed_content
    assert "Anotação pessoal do aluno feita em sala." in reprocessed_content


def test_lesson_update_preserves_everything_outside_generated_block(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """User metadata and notes before and after the generated block are untouched."""
    path = write_lesson_page(tmp_path, sample_lesson_output)
    original = path.read_text(encoding="utf-8")
    original = original.replace("tags:\n", "custom: valor pessoal\ntags:\n  - minha/tag\n")
    original = original.replace(
        "<!-- AUTO-CONTENT:START -->", "Observação antes.\n\n<!-- AUTO-CONTENT:START -->"
    )
    original += "\nAnotação depois.\n"
    path.write_text(original, encoding="utf-8")
    before, tail = original.split("<!-- AUTO-CONTENT:START -->")
    _, after = tail.split("<!-- AUTO-CONTENT:END -->")

    output = sample_lesson_output.model_copy(update={"body_markdown": "Novo corpo."})
    write_lesson_page(tmp_path, output)

    updated = path.read_text(encoding="utf-8")
    updated_before, updated_tail = updated.split("<!-- AUTO-CONTENT:START -->")
    block, updated_after = updated_tail.split("<!-- AUTO-CONTENT:END -->")
    assert updated_before == before
    assert updated_after == after
    assert "Novo corpo." in block


@pytest.mark.parametrize(
    "surviving_marker", ["", "<!-- AUTO-CONTENT:START -->", "<!-- AUTO-CONTENT:END -->"]
)
def test_lesson_force_recovery_preserves_all_text_and_is_idempotent(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
    surviving_marker: str,
) -> None:
    """A damaged file retains its existing text and gains a separate generated block."""
    path = write_lesson_page(tmp_path, sample_lesson_output)
    original = (
        f"# Aula\n\nNota antes.\n{surviving_marker}\nTrecho antigo ou manual.\n\nNota final.\n"
    )
    path.write_text(original, encoding="utf-8")

    write_lesson_page(tmp_path, sample_lesson_output, force=True)
    healed = path.read_text(encoding="utf-8")
    assert (
        original.replace(surviving_marker, "", 1) in healed
        if surviving_marker
        else original in healed
    )
    assert healed.count("<!-- AUTO-CONTENT:START -->") == 1
    assert healed.count("<!-- AUTO-CONTENT:END -->") == 1
    assert sample_lesson_output.body_markdown.strip() in healed

    write_lesson_page(tmp_path, sample_lesson_output, force=True)
    assert path.read_text(encoding="utf-8") == healed


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize(
    "markers",
    [
        "<!-- AUTO-CONTENT:END -->\n<!-- AUTO-CONTENT:START -->",
        "<!-- AUTO-CONTENT:START -->\n<!-- AUTO-CONTENT:START -->\n<!-- AUTO-CONTENT:END -->",
        "<!-- AUTO-CONTENT:START -->\n<!-- AUTO-CONTENT:END -->\n<!-- AUTO-CONTENT:END -->",
    ],
)
def test_lesson_rejects_ambiguous_markers_without_changing_file(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
    markers: str,
    force: bool,
) -> None:
    """Ambiguous delimiter layouts must not risk deleting or duplicating notes."""
    path = write_lesson_page(tmp_path, sample_lesson_output)
    original = f"Cabeçalho pessoal.\n{markers}\nNotas pessoais.\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="[Dd]elimit"):
        write_lesson_page(tmp_path, sample_lesson_output, force=force)
    assert path.read_text(encoding="utf-8") == original


def test_write_atomic_zettel_creates_and_updates_idempotently(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_atomic_zettel writes Zettel notes, merges tags, and avoids duplicate links.

    Args:
        tmp_path: Pytest temporary directory.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    zettel = sample_lesson_output.extracted_zettels[0]

    # 1. First write from Lesson 1
    zettel_path = write_atomic_zettel(
        vault_root=tmp_path,
        zettel=zettel,
        output=sample_lesson_output,
    )
    assert zettel_path.is_file()
    assert zettel_path.name == "valor-presente-liquido.md"

    initial_content = zettel_path.read_text(encoding="utf-8")
    assert "type: zettel" in initial_content
    assert 'slug: "valor-presente-liquido"' in initial_content
    assert "- [[taxa-interna-retorno]]" in initial_content
    assert "<!-- AUTO-BACKLINKS:START -->" in initial_content
    assert "- [[Aula_01_criterios-decisao]] (Finanças Corporativas)" in initial_content

    # 2. Reprocess same lesson - verify no duplicate backlinks
    write_atomic_zettel(
        vault_root=tmp_path,
        zettel=zettel,
        output=sample_lesson_output,
    )
    reprocessed_content = zettel_path.read_text(encoding="utf-8")
    assert reprocessed_content.count("- [[Aula_01_criterios-decisao]] (Finanças Corporativas)") == 1

    # 3. Reference from Lesson 2 with an additional domain tag
    zettel_updated_tags = zettel.model_copy(
        update={"domain_tags": ["financas", "gestao-estrategica"]}
    )
    lesson_2 = sample_lesson_output.model_copy(
        update={
            "lesson_number": 2,
            "lesson_title": "Taxa Interna de Retorno",
            "lesson_slug": "taxa-interna-retorno",
        }
    )
    write_atomic_zettel(
        vault_root=tmp_path,
        zettel=zettel_updated_tags,
        output=lesson_2,
    )
    multi_lesson_content = zettel_path.read_text(encoding="utf-8")
    assert "- [[Aula_01_criterios-decisao]] (Finanças Corporativas)" in multi_lesson_content
    assert "- [[Aula_02_taxa-interna-retorno]] (Finanças Corporativas)" in multi_lesson_content
    assert "gestao-estrategica" in multi_lesson_content
    assert "orcamento-capital" in multi_lesson_content


def test_write_audit_report_persists_valid_json(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_audit_report generates a validated JSON file in 03_Auditoria_Factual.

    Args:
        tmp_path: Pytest temporary directory.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    report_path = write_audit_report(vault_root=tmp_path, output=sample_lesson_output)
    assert report_path.is_file()
    assert report_path.name == "financas-corporativas_Aula_01_audit.json"

    data = json.loads(report_path.read_text(encoding="utf-8"))
    report = LessonAuditReport.model_validate(data)
    assert report.discipline_slug == "financas-corporativas"
    assert report.lesson_number == 1
    assert report.fact_check_passed is True
    assert report.total_claims_audited == 1
    assert len(report.audit_items) == 1
    assert report.audit_items[0].claim_id == "CLM-001"


def test_export_lesson_to_vault_coordinates_all_files(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that export_lesson_to_vault exports all artifacts and remains fully idempotent.

    Args:
        tmp_path: Pytest temporary directory.
        sample_syllabus: Sample syllabus module fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    result = export_lesson_to_vault(
        vault_root=tmp_path,
        output=sample_lesson_output,
        syllabus=sample_syllabus,
    )

    assert isinstance(result, VaultExportResult)
    assert result.lesson_path.is_file()
    assert result.index_path.is_file()
    assert len(result.zettel_paths) == 1
    assert result.audit_report_path.is_file()

    # Second run to prove idempotency across entire bundle
    second_result = export_lesson_to_vault(
        vault_root=tmp_path,
        output=sample_lesson_output,
        syllabus=sample_syllabus,
    )
    assert second_result.lesson_path == result.lesson_path
    assert second_result.index_path == result.index_path

    # Verify index links are not duplicated
    index_text = result.index_path.read_text(encoding="utf-8")
    expected_link = "- [[Aula_01_criterios-decisao|Aula 01: Critérios de Decisão de Investimento]]"
    assert index_text.count(expected_link) == 1


def test_format_zettels_section_empty() -> None:
    """Tests that format_zettels_section returns an empty string when zettels list is empty.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    assert format_zettels_section([]) == ""


def test_write_discipline_index_missing_delimiters_raises(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_discipline_index raises ValueError if delimiters are corrupted or missing.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_syllabus: Sample syllabus module fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    discipline_dir = tmp_path / "01_Wiki_Disciplinas" / sample_syllabus.discipline_slug
    discipline_dir.mkdir(parents=True, exist_ok=True)
    index_path = discipline_dir / "_Indice_Materia.md"
    index_path.write_text("Arquivo sem delimitadores de auto-lessons.", encoding="utf-8")

    with pytest.raises(ValueError, match="Delimiters .* not found"):
        write_discipline_index(
            vault_root=tmp_path,
            syllabus=sample_syllabus,
            output=sample_lesson_output,
        )


def test_write_lesson_page_missing_delimiters_raises(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_lesson_page raises ValueError if AUTO-CONTENT delimiters are missing.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    discipline_dir = tmp_path / "01_Wiki_Disciplinas" / sample_lesson_output.discipline_slug
    discipline_dir.mkdir(parents=True, exist_ok=True)
    lesson_path = (
        discipline_dir
        / f"Aula_{sample_lesson_output.lesson_number:02d}_{sample_lesson_output.lesson_slug}.md"
    )
    lesson_path.write_text("Arquivo corrompido sem tags auto-content.", encoding="utf-8")

    with pytest.raises(ValueError, match="Delimiters .* not found"):
        write_lesson_page(vault_root=tmp_path, output=sample_lesson_output)


def test_write_atomic_zettel_missing_delimiters_raises(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_atomic_zettel raises ValueError if AUTO-BACKLINKS delimiters are missing.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    zettel = sample_lesson_output.extracted_zettels[0]
    zettel_dir = tmp_path / "02_Zettelkasten"
    zettel_dir.mkdir(parents=True, exist_ok=True)
    zettel_path = zettel_dir / f"{zettel.slug}.md"
    zettel_path.write_text("Arquivo de zettel sem tags delimitadoras.", encoding="utf-8")

    with pytest.raises(ValueError, match="Delimiters .* not found"):
        write_atomic_zettel(vault_root=tmp_path, zettel=zettel, output=sample_lesson_output)


def test_write_atomic_zettel_crlf_safe_no_duplicate_frontmatter(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that existing files with CRLF line endings do not produce duplicate frontmatter.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    zettel = sample_lesson_output.extracted_zettels[0]
    zettel_dir = tmp_path / "02_Zettelkasten"
    zettel_dir.mkdir(parents=True, exist_ok=True)
    zettel_path = zettel_dir / f"{zettel.slug}.md"

    # Write initial file with explicit Windows CRLF line endings
    crlf_content = (
        "---\r\n"
        "type: zettel\r\n"
        f'slug: "{zettel.slug}"\r\n'
        f'title: "{zettel.title}"\r\n'
        "tags:\r\n"
        "  - financas\r\n"
        "---\r\n\r\n"
        f"# {zettel.title}\r\n\r\n"
        "Texto conceitual com CRLF.\r\n\r\n"
        "## Conexoes Diretas\r\n"
        "- [[link-antigo]]\r\n\r\n"
        "## Referencias no Curso\r\n"
        "<!-- AUTO-BACKLINKS:START -->\r\n"
        "- [[Aula_00_intro]] (Introdução)\r\n"
        "<!-- AUTO-BACKLINKS:END -->\r\n"
    )
    zettel_path.write_bytes(crlf_content.encode("utf-8"))

    # Reprocess zettel
    updated_path = write_atomic_zettel(
        vault_root=tmp_path,
        zettel=zettel,
        output=sample_lesson_output,
    )
    content = updated_path.read_text(encoding="utf-8")

    # Frontmatter must not be duplicated
    assert content.count("type: zettel") == 1
    assert content.count("---") == 2
    assert "<!-- AUTO-BACKLINKS:START -->" in content
    assert "- [[Aula_00_intro]]" in content
    expected_backlink = (
        f"- [[Aula_{sample_lesson_output.lesson_number:02d}_{sample_lesson_output.lesson_slug}]]"
    )
    assert expected_backlink in content


def test_write_lesson_page_escapes_quotes_in_yaml(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that double quotes in lesson titles are escaped in YAML frontmatter.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    quoted_output = sample_lesson_output.model_copy(
        update={"lesson_title": 'Critérios de "Valuation" e M&A'}
    )
    lesson_path = write_lesson_page(vault_root=tmp_path, output=quoted_output)
    content = lesson_path.read_text(encoding="utf-8")

    assert 'lesson_title: "Critérios de \\"Valuation\\" e M&A"' in content


def test_write_atomic_zettel_merges_new_related_links(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that reprocessing an atomic zettel merges new related links into Conexoes Diretas.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    zettel = sample_lesson_output.extracted_zettels[0]

    # First write with initial related links
    zettel_initial = zettel.model_copy(update={"related_links": ["taxa-interna-retorno"]})
    write_atomic_zettel(vault_root=tmp_path, zettel=zettel_initial, output=sample_lesson_output)

    # Second write with an additional related link
    zettel_expanded = zettel.model_copy(
        update={"related_links": ["taxa-interna-retorno", "custo-capital-wacc"]}
    )
    lesson_2 = sample_lesson_output.model_copy(
        update={"lesson_number": 2, "lesson_title": "Aula 02"}
    )
    updated_path = write_atomic_zettel(
        vault_root=tmp_path,
        zettel=zettel_expanded,
        output=lesson_2,
    )
    content = updated_path.read_text(encoding="utf-8")

    assert "- [[taxa-interna-retorno]]" in content
    assert "- [[custo-capital-wacc]]" in content
    assert content.count("- [[taxa-interna-retorno]]") == 1


def test_write_dialectical_tension_creates_new_note(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests creation of a new dialectical tension markdown note.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    tension = DialecticalTension(
        slug="eficiencia-vs-resiliencia",
        title="Eficiência de Giro vs Resiliência Operacional",
        pole_a_discipline="operacoes",
        pole_a_framework="Just-in-Time",
        pole_a_thesis="Minimizar estoques e custos de armazenagem.",
        pole_b_discipline="estrategia",
        pole_b_framework="Gestão de Riscos",
        pole_b_thesis="Manter estoques de segurança contra choques.",
        tension_nature="Curto Prazo vs Longo Prazo",
        synthesis_guidelines="Adotar políticas de dual sourcing e estoques estratégicos.",
        related_zettel_slugs=["just-in-time", "capital-de-giro"],
    )

    tension_path = write_dialectical_tension(
        vault_root=tmp_path,
        tension=tension,
        output=sample_lesson_output,
    )

    assert tension_path.is_file()
    assert tension_path.parent.name == "04_Diario_Tensoes"
    content = tension_path.read_text(encoding="utf-8")

    assert 'type: "diario_tensao"' in content or "type: diario_tensao" in content
    assert 'slug: "eficiencia-vs-resiliencia"' in content
    assert "# Eficiência de Giro vs Resiliência Operacional" in content
    assert "Curto Prazo vs Longo Prazo" in content
    assert "Just-in-Time" in content
    assert "Gestão de Riscos" in content
    assert "- [[just-in-time]]" in content
    assert "- [[capital-de-giro]]" in content
    assert "<!-- AUTO-EVIDENCES:START -->" in content
    assert "<!-- AUTO-EVIDENCES:END -->" in content
    assert (
        f"- [[Aula_{sample_lesson_output.lesson_number:02d}_{sample_lesson_output.lesson_slug}]]"
        in content
    )
    assert "## Anotações Pessoais e Resoluções Práticas" in content


def test_write_dialectical_tension_idempotent_accumulation(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that multiple lessons accumulate evidence idempotently without clobbering notes.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    tension = DialecticalTension(
        slug="centralizacao-vs-autonomia",
        title="Centralização vs Autonomia",
        pole_a_discipline="organizacao",
        pole_a_framework="Estrutura Hierárquica",
        pole_a_thesis="Padronização e controle centralizado.",
        pole_b_discipline="inovacao",
        pole_b_framework="Squads Ágeis",
        pole_b_thesis="Velocidade e descentralização de decisões.",
        tension_nature="Controle vs Velocidade",
        synthesis_guidelines="Autonomia com alinhamento e guardrails claros.",
        related_zettel_slugs=["hierarquia"],
    )

    # 1. First lesson writes tension
    path = write_dialectical_tension(
        vault_root=tmp_path,
        tension=tension,
        output=sample_lesson_output,
    )

    # User adds manual personal notes
    content = path.read_text(encoding="utf-8")
    manual_annotation = "\nMinha nota manual: aplicar alinhamento no comitê trimestral.\n"
    path.write_text(content + manual_annotation, encoding="utf-8")

    # 2. Second lesson updates the same tension with new related zettel
    expanded_tension = tension.model_copy(
        update={"related_zettel_slugs": ["hierarquia", "squads-ageis"]}
    )
    lesson_2 = sample_lesson_output.model_copy(
        update={
            "lesson_number": 2,
            "lesson_title": "Modelos Ágeis",
            "lesson_slug": "modelos-ageis",
        }
    )
    write_dialectical_tension(
        vault_root=tmp_path,
        tension=expanded_tension,
        output=lesson_2,
    )

    # 3. Re-run lesson 2 to verify idempotency (no duplicate entries)
    updated_path = write_dialectical_tension(
        vault_root=tmp_path,
        tension=expanded_tension,
        output=lesson_2,
    )

    updated_content = updated_path.read_text(encoding="utf-8")

    # Verify both lessons are recorded exactly once
    lesson_1_link = (
        f"- [[Aula_{sample_lesson_output.lesson_number:02d}_{sample_lesson_output.lesson_slug}]]"
    )
    assert lesson_1_link in updated_content
    assert "- [[Aula_02_modelos-ageis]]" in updated_content
    assert updated_content.count("- [[Aula_02_modelos-ageis]]") == 1

    # Verify zettels were merged
    assert "- [[hierarquia]]" in updated_content
    assert "- [[squads-ageis]]" in updated_content
    assert updated_content.count("- [[hierarquia]]") == 1

    # Verify manual notes were strictly preserved
    assert "Minha nota manual: aplicar alinhamento no comitê trimestral." in updated_content


def test_write_tensions_index_creates_and_merges(tmp_path: Path) -> None:
    """Tests creating and updating the tensions index MOC file (_Indice_Tensoes.md).

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    t1 = DialecticalTension(
        slug="eficiencia-vs-resiliencia",
        title="Eficiência vs Resiliência",
        pole_a_discipline="operacoes",
        pole_a_framework="JIT",
        pole_a_thesis="Estoque zero.",
        pole_b_discipline="estrategia",
        pole_b_framework="Resiliência",
        pole_b_thesis="Estoque de segurança.",
        tension_nature="Curto vs Longo Prazo",
        synthesis_guidelines="Dual sourcing.",
    )
    t2 = DialecticalTension(
        slug="custo-vs-diferenciacao",
        title="Custo vs Diferenciação",
        pole_a_discipline="estrategia",
        pole_a_framework="Liderança em Custo",
        pole_a_thesis="Preço baixo.",
        pole_b_discipline="marketing",
        pole_b_framework="Diferenciação",
        pole_b_thesis="Premium de preço.",
        tension_nature="Volume vs Margem",
        synthesis_guidelines="Segmentação seletiva.",
    )

    # Initial write with t1
    index_path = write_tensions_index(vault_root=tmp_path, tensions=[t1])
    assert index_path.is_file()
    assert index_path.name == "_Indice_Tensoes.md"

    content = index_path.read_text(encoding="utf-8")
    assert "- [[eficiencia-vs-resiliencia|Eficiência vs Resiliência]]" in content
    assert "<!-- AUTO-TENSIONS:START -->" in content
    assert "<!-- AUTO-TENSIONS:END -->" in content

    # Add manual note
    manual_note = "\n\nMinha reflexão executiva global.\n"
    index_path.write_text(content + manual_note, encoding="utf-8")

    # Update with t1 and t2
    write_tensions_index(vault_root=tmp_path, tensions=[t1, t2])
    updated_content = index_path.read_text(encoding="utf-8")

    assert "- [[eficiencia-vs-resiliencia|Eficiência vs Resiliência]]" in updated_content
    assert "- [[custo-vs-diferenciacao|Custo vs Diferenciação]]" in updated_content
    assert updated_content.count("- [[eficiencia-vs-resiliencia|Eficiência vs Resiliência]]") == 1
    assert "Minha reflexão executiva global." in updated_content


def test_export_lesson_to_vault_with_tensions(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
    sample_syllabus: SyllabusModule,
) -> None:
    """Tests that export_lesson_to_vault persists dialectical tensions when present.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.
        sample_syllabus: Sample syllabus fixture.

    Returns:
        None.

    Raises:
        None.
    """
    tension = DialecticalTension(
        slug="caixa-vs-crescimento",
        title="Caixa vs Crescimento",
        pole_a_discipline="financas",
        pole_a_framework="Fluxo de Caixa Livre",
        pole_a_thesis="Foco em solvência.",
        pole_b_discipline="estrategia",
        pole_b_framework="Blitzscaling",
        pole_b_thesis="Queima rápida de caixa para market share.",
        tension_nature="Liquidez vs Expansão",
        synthesis_guidelines="Monitorar runway mínimo de 18 meses.",
    )
    lesson_with_tension = sample_lesson_output.model_copy(update={"detected_tensions": [tension]})

    result = export_lesson_to_vault(
        vault_root=tmp_path,
        output=lesson_with_tension,
        syllabus=sample_syllabus,
    )

    assert len(result.tension_paths) == 1
    assert result.tension_paths[0].name == "caixa-vs-crescimento.md"
    assert result.tensions_index_path is not None
    assert result.tensions_index_path.name == "_Indice_Tensoes.md"
    assert result.tension_paths[0].is_file()
    assert result.tensions_index_path.is_file()


def test_write_discipline_index_force_auto_heals_missing_delimiters(
    tmp_path: Path,
    sample_syllabus: SyllabusModule,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_discipline_index auto-recovers missing delimiters when force=True.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_syllabus: Sample syllabus module fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    discipline_dir = tmp_path / "01_Wiki_Disciplinas" / sample_syllabus.discipline_slug
    discipline_dir.mkdir(parents=True, exist_ok=True)
    index_path = discipline_dir / "_Indice_Materia.md"
    # File without AUTO-LESSONS delimiters
    index_path.write_text(
        "# Finanças Corporativas\n\nMinha anotação manual sobrevivente.",
        encoding="utf-8",
    )

    updated_path = write_discipline_index(
        vault_root=tmp_path,
        syllabus=sample_syllabus,
        output=sample_lesson_output,
        force=True,
    )
    content = updated_path.read_text(encoding="utf-8")
    assert "<!-- AUTO-LESSONS:START -->" in content
    assert "<!-- AUTO-LESSONS:END -->" in content
    assert "Aula 01: Critérios de Decisão de Investimento" in content
    assert "Minha anotação manual sobrevivente." in content


def test_write_lesson_page_force_auto_heals_missing_delimiters_and_preserves_notes(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_lesson_page auto-heals corrupted delimiters and preserves manual notes.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    discipline_dir = tmp_path / "01_Wiki_Disciplinas" / sample_lesson_output.discipline_slug
    discipline_dir.mkdir(parents=True, exist_ok=True)
    lesson_path = (
        discipline_dir
        / f"Aula_{sample_lesson_output.lesson_number:02d}_{sample_lesson_output.lesson_slug}.md"
    )
    # File where AUTO-CONTENT delimiters were deleted, but personal notes exist
    corrupted_content = (
        "# Aula 01: Critérios\n\n"
        "Texto antigo sem delimitadores.\n\n"
        "## Notas Pessoais de Aula\n"
        "Minhas anotações particulares de alto valor.\n"
    )
    lesson_path.write_text(corrupted_content, encoding="utf-8")

    updated_path = write_lesson_page(
        vault_root=tmp_path,
        output=sample_lesson_output,
        force=True,
    )
    content = updated_path.read_text(encoding="utf-8")
    assert "<!-- AUTO-CONTENT:START -->" in content
    assert "<!-- AUTO-CONTENT:END -->" in content
    assert sample_lesson_output.body_markdown.strip() in content
    assert "Minhas anotações particulares de alto valor." in content


def test_write_atomic_zettel_force_auto_heals_missing_delimiters(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Tests that write_atomic_zettel auto-heals missing AUTO-BACKLINKS delimiters when force=True.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_lesson_output: Sample lesson output fixture.

    Returns:
        None.

    Raises:
        None.
    """
    zettel = sample_lesson_output.extracted_zettels[0]
    zettel_dir = tmp_path / "02_Zettelkasten"
    zettel_dir.mkdir(parents=True, exist_ok=True)
    zettel_path = zettel_dir / f"{zettel.slug}.md"
    corrupted_content = (
        "---\ntype: zettel\nslug: valor-presente-liquido\n---\n\n"
        "# VPL\n\nConceito intacto sem delimitadores de backlinks.\n"
    )
    zettel_path.write_text(corrupted_content, encoding="utf-8")

    updated_path = write_atomic_zettel(
        vault_root=tmp_path,
        zettel=zettel,
        output=sample_lesson_output,
        force=True,
    )
    content = updated_path.read_text(encoding="utf-8")
    assert "<!-- AUTO-BACKLINKS:START -->" in content
    assert "<!-- AUTO-BACKLINKS:END -->" in content
    assert "Aula_01_criterios-decisao" in content
    assert "Conceito intacto sem delimitadores de backlinks." in content


def test_write_lesson_page_renders_pending_review_callout_and_frontmatter(tmp_path: Path) -> None:
    """Exports lesson page with pending_review frontmatter and warning callout."""
    from datetime import date

    from cathedra.exporters.obsidian_writer import write_lesson_page
    from cathedra.schemas import ClaimAuditItem, WikiLessonOutput

    output = WikiLessonOutput(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        lesson_number=1,
        lesson_title="Introdução",
        lesson_slug="introducao",
        processed_date=date(2026, 11, 20),
        source_slide_filename="01.pdf",
        fact_check_passed=True,
        has_pending_review=True,
        removed_unsupported_claims=0,
        body_markdown="Conteúdo principal.",
        extracted_zettels=[],
        audit_items=[
            ClaimAuditItem(
                claim_id="C01",
                quote="Afirmação sem localizador literal.",
                category="technical",
                verdict="verified",
                evidence_status="pending_review",
            )
        ],
    )

    lesson_path = write_lesson_page(vault_root=tmp_path, output=output)
    content = lesson_path.read_text(encoding="utf-8")
    assert "fact_check_status: pending_review" in content
    assert "> [!warning] Revisão Factual Pendente" in content
    assert "`C01` (verified): Afirmação sem localizador literal." in content


def test_write_lesson_page_updates_managed_frontmatter_and_exports_cross_links(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Reprocessing updates managed audit frontmatter keys and renders cross_links."""
    from cathedra.schemas import CrossDisciplineLink

    initial = sample_lesson_output.model_copy(
        update={
            "has_pending_review": True,
            "removed_unsupported_claims": 2,
            "cross_links": [
                CrossDisciplineLink(
                    target_discipline_slug="estrategia",
                    target_topic="Vantagem Competitiva",
                    connection_type="synergy",
                    description="VPL positivo sustenta investimentos de diferenciação.",
                )
            ],
        }
    )
    lesson_path = write_lesson_page(vault_root=tmp_path, output=initial)
    first_content = lesson_path.read_text(encoding="utf-8")
    assert "fact_check_status: pending_review" in first_content
    assert "## Conexoes Transversais no Curriculo" in first_content
    expected_link = "[[01_Wiki_Disciplinas/estrategia/_Indice_Materia|Vantagem Competitiva]]"
    assert expected_link in first_content

    # Inject a custom user YAML key and reprocess as clean verified
    lesson_path.write_text(
        first_content.replace("tags:\n", "owner: meu-estudo\ntags:\n"),
        encoding="utf-8",
    )
    resolved = initial.model_copy(
        update={
            "has_pending_review": False,
            "removed_unsupported_claims": 0,
            "processed_date": date(2026, 11, 21),
        }
    )
    write_lesson_page(vault_root=tmp_path, output=resolved)
    updated = lesson_path.read_text(encoding="utf-8")
    assert "fact_check_status: verified" in updated
    assert "removed_claims: 0" in updated
    assert "processed_date: 2026-11-21" in updated
    assert "owner: meu-estudo" in updated


def test_write_atomic_zettel_force_repairs_legacy_corrupted_body_preserving_links(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Running write_atomic_zettel with force=True repairs legacy body without losing links."""
    zettel_dir = tmp_path / "02_Zettelkasten"
    zettel_dir.mkdir(parents=True)
    zettel_path = zettel_dir / "valor-presente-liquido.md"
    zettel_path.write_text(
        "---\n"
        "type: zettel\n"
        'slug: "valor-presente-liquido"\n'
        'title: "Valor Presente Líquido"\n'
        "custom: nota-minha\n"
        "tags:\n"
        "  - financas\n"
        "---\n\n"
        "# Valor Presente Líquido\n\n"
        "Texto legado corrompido.\\n\\n- **Item:** quebrado.\n\n"
        "## Conexoes Diretas\n"
        "- [[taxa-interna-retorno]]\n\n"
        "## Referencias no Curso\n"
        "<!-- AUTO-BACKLINKS:START -->\n"
        "- [[Aula_01_criterios-de-decisao]] (Finanças Corporativas)\n"
        "<!-- AUTO-BACKLINKS:END -->\n",
        encoding="utf-8",
    )

    repaired_zettel = sample_lesson_output.extracted_zettels[0].model_copy(
        update={"content_markdown": "Texto limpo e corrigido em prosa contínua."}
    )
    write_atomic_zettel(
        vault_root=tmp_path,
        zettel=repaired_zettel,
        output=sample_lesson_output,
        force=True,
    )
    updated = zettel_path.read_text(encoding="utf-8")
    assert "Texto limpo e corrigido em prosa contínua." in updated
    assert "Texto legado corrompido" not in updated
    assert "<!-- AUTO-CONTENT:START -->" in updated
    assert "custom: nota-minha" in updated
    assert "- [[taxa-interna-retorno]]" in updated
    assert "- [[Aula_01_criterios-de-decisao]] (Finanças Corporativas)" in updated


def test_write_audit_report_persists_has_pending_review(
    tmp_path: Path,
    sample_lesson_output: WikiLessonOutput,
) -> None:
    """Persisted LessonAuditReport JSON records has_pending_review faithfully."""
    pending_output = sample_lesson_output.model_copy(update={"has_pending_review": True})
    report_path = write_audit_report(vault_root=tmp_path, output=pending_output)
    restored = LessonAuditReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert restored.has_pending_review is True

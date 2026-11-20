"""Unit tests for batch binding of existing transcript JSONs to the structured syllabus."""

from datetime import UTC, datetime
from pathlib import Path

from mba_wiki.schemas import (
    StructuredSyllabus,
    SyllabusModule,
    TranscriptCheckpoint,
    VideoTranscript,
)
from mba_wiki.transcription.binder import bind_transcripts_to_syllabus


def _make_syllabus() -> StructuredSyllabus:
    return StructuredSyllabus(
        modules=[
            SyllabusModule(
                discipline_slug="fundamentos-de-estatistica",
                discipline_name="Fundamentos de Estatística",
                syllabus_summary="Conceitos basicos.",
                topics=["Probabilidade"],
                bibliography=["Favero"],
            ),
            SyllabusModule(
                discipline_slug="series-temporais",
                discipline_name="Séries Temporais",
                syllabus_summary="Modelagem temporal.",
                topics=["ARIMA"],
                bibliography=["Morettin"],
            ),
        ],
    )


def _write_transcript(
    path: Path,
    *,
    source_filename: str,
    discipline_slug: str,
    lesson_number: int | None = None,
    with_checkpoint: bool = False,
) -> VideoTranscript:
    checkpoint = (
        TranscriptCheckpoint(
            source_relative_path=f"{discipline_slug}/{source_filename}",
            source_size_bytes=1024,
            source_sha256="a" * 64,
            model_name="large-v3",
            device="cuda",
            compute_type="int8_float16",
            language="pt",
            vad_filter=True,
            beam_size=5,
            engine_version="1.2.1",
            pipeline_revision="etapa-38-v1",
        )
        if with_checkpoint
        else None
    )
    transcript = VideoTranscript(
        source_filename=source_filename,
        discipline_slug=discipline_slug,
        lesson_number=lesson_number,
        duration_seconds=120.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime(2026, 11, 9, 2, 0, tzinfo=UTC),
        full_text_raw="texto bruto",
        full_text_cleaned="texto limpo",
        segments=[],
        checkpoint=checkpoint,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    return transcript


def test_bind_transcripts_updates_legacy_slug_and_lesson_number_preserving_checkpoint(
    tmp_path: Path,
) -> None:
    """Updates legacy discipline_slug and lesson_number while keeping checkpoint intact."""
    syllabus = _make_syllabus()
    transcripts_dir = tmp_path / "transcripts"
    slides_dir = tmp_path / "slides"

    t1_path = (
        transcripts_dir / "fundamentos-de-estatistica" / "01-Fundamentos-de-Estatistica-I.json"
    )
    t2_path = (
        transcripts_dir / "fundamentos-de-estatistica" / "02-Fundamentos-de-Estatistica-II.json"
    )
    _write_transcript(
        t1_path,
        source_filename="01-Fundamentos-de-Estatistica-I.mp4",
        discipline_slug="módulo-01-fundamentos",
        lesson_number=None,
        with_checkpoint=True,
    )
    _write_transcript(
        t2_path,
        source_filename="02-Fundamentos-de-Estatistica-II.mp4",
        discipline_slug="módulo-01-fundamentos",
        lesson_number=None,
        with_checkpoint=False,
    )

    (slides_dir / "fundamentos-de-estatistica").mkdir(parents=True)
    (slides_dir / "fundamentos-de-estatistica" / "01-Fundamentos-de-Estatistica-I.pdf").write_bytes(
        b"%PDF"
    )
    (
        slides_dir / "fundamentos-de-estatistica" / "02-Fundamentos-de-Estatistica-II.pdf"
    ).write_bytes(b"%PDF")

    summary = bind_transcripts_to_syllabus(
        syllabus=syllabus,
        transcripts_dir=transcripts_dir,
        slides_dir=slides_dir,
        dry_run=False,
    )

    assert summary.total_files_scanned == 2
    assert len(summary.updated_files) == 2
    assert summary.already_bound_count == 0
    assert summary.unmatched_folders == []
    assert summary.ambiguous_files == []
    assert summary.unnumbered_files == []
    assert summary.warnings == []

    updated_1 = VideoTranscript.model_validate_json(t1_path.read_text(encoding="utf-8"))
    updated_2 = VideoTranscript.model_validate_json(t2_path.read_text(encoding="utf-8"))
    assert updated_1.discipline_slug == "fundamentos-de-estatistica"
    assert updated_1.lesson_number == 1
    assert updated_1.checkpoint is not None
    assert updated_1.checkpoint.source_sha256 == "a" * 64
    assert updated_2.discipline_slug == "fundamentos-de-estatistica"
    assert updated_2.lesson_number == 2


def test_bind_transcripts_dry_run_does_not_modify_files(tmp_path: Path) -> None:
    """Dry run reports planned updates without modifying JSON files on disk."""
    syllabus = _make_syllabus()
    transcripts_dir = tmp_path / "transcripts"
    t_path = transcripts_dir / "fundamentos-de-estatistica" / "01-Aula.json"
    _write_transcript(
        t_path,
        source_filename="01-Aula.mp4",
        discipline_slug="módulo-01-fundamentos",
        lesson_number=None,
    )
    original_bytes = t_path.read_bytes()

    summary = bind_transcripts_to_syllabus(
        syllabus=syllabus,
        transcripts_dir=transcripts_dir,
        slides_dir=None,
        dry_run=True,
    )

    assert len(summary.updated_files) == 1
    assert t_path.read_bytes() == original_bytes


def test_bind_transcripts_reports_unmatched_ambiguous_unnumbered_and_slide_mismatch(
    tmp_path: Path,
) -> None:
    """Reports non-syllabus folders, duplicate lesson numbers, missing prefixes, and slide gaps."""
    syllabus = _make_syllabus()
    transcripts_dir = tmp_path / "transcripts"
    slides_dir = tmp_path / "slides"

    _write_transcript(
        transcripts_dir / "palestras" / "01-Palestra-IA.json",
        source_filename="01-Palestra-IA.mp4",
        discipline_slug="palestras",
    )
    _write_transcript(
        transcripts_dir / "series-temporais" / "01-Parte-A.json",
        source_filename="01-Parte-A.mp4",
        discipline_slug="series-temporais",
    )
    _write_transcript(
        transcripts_dir / "series-temporais" / "01-Parte-B.json",
        source_filename="01-Parte-B.mp4",
        discipline_slug="series-temporais",
    )
    _write_transcript(
        transcripts_dir / "series-temporais" / "02-Daniel-Godoy-Zanco.json",
        source_filename="02-Daniel-Godoy-Zanco.mp4",
        discipline_slug="series-temporais",
    )
    _write_transcript(
        transcripts_dir / "series-temporais" / "Aula-Sem-Numero.json",
        source_filename="Aula-Sem-Numero.mp4",
        discipline_slug="series-temporais",
    )

    (slides_dir / "series-temporais").mkdir(parents=True)
    (slides_dir / "series-temporais" / "01-Series-Temporais-I.pdf").write_bytes(b"%PDF")

    summary = bind_transcripts_to_syllabus(
        syllabus=syllabus,
        transcripts_dir=transcripts_dir,
        slides_dir=slides_dir,
        dry_run=False,
    )

    assert summary.unmatched_folders == ["palestras"]
    assert len(summary.ambiguous_files) == 2
    assert len(summary.unnumbered_files) == 1
    assert len(summary.updated_files) == 1
    assert summary.updated_files[0].lesson_number == 2
    assert any("02" in warning for warning in summary.warnings)

    part_a = VideoTranscript.model_validate_json(
        (transcripts_dir / "series-temporais" / "01-Parte-A.json").read_text(encoding="utf-8")
    )
    assert part_a.lesson_number is None


def test_bind_transcripts_is_idempotent_on_already_bound_files(tmp_path: Path) -> None:
    """Second run counts already bound files without rewriting them."""
    syllabus = _make_syllabus()
    transcripts_dir = tmp_path / "transcripts"
    t_path = transcripts_dir / "fundamentos-de-estatistica" / "03-Aula.json"
    _write_transcript(
        t_path,
        source_filename="03-Aula.mp4",
        discipline_slug="fundamentos-de-estatistica",
        lesson_number=3,
    )

    summary = bind_transcripts_to_syllabus(
        syllabus=syllabus,
        transcripts_dir=transcripts_dir,
        slides_dir=None,
        dry_run=False,
    )

    assert summary.total_files_scanned == 1
    assert summary.updated_files == []
    assert summary.already_bound_count == 1

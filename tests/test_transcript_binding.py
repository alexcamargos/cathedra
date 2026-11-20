"""Offline tests for safe transcript selection and audit provenance."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import Result
from pydantic import ValidationError
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from cathedra.agents.graph import ingestion_node
from cathedra.cli import app
from cathedra.schemas import (
    AuditClaimsResponse,
    ClaimAuditItem,
    DraftResult,
    LessonAuditReport,
    SlideChunk,
    StructuredSyllabus,
    SyllabusModule,
    VideoTranscript,
)
from tests.conftest import FakeLLMClient


@pytest.fixture
def module() -> SyllabusModule:
    return SyllabusModule(
        discipline_slug="financas",
        discipline_name="Finanças",
        syllabus_summary="Finanças",
        topics=[],
        bibliography=[],
    )


@pytest.fixture
def transcript() -> VideoTranscript:
    return VideoTranscript(
        source_filename="video-aula.mp4",
        discipline_slug="financas",
        duration_seconds=30,
        model_name="teste",
        compute_type="cpu",
        processed_at=datetime(2026, 1, 1, tzinfo=UTC),
        full_text_raw="Aula gravada.",
        full_text_cleaned="Aula gravada.",
        segments=[],
    )


def write_transcript(path: Path, transcript: VideoTranscript, lesson_number: int | None) -> None:
    payload = transcript.model_dump(mode="json")
    if lesson_number is not None:
        payload["lesson_number"] = lesson_number
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
    module: SyllabusModule,
) -> tuple[Path, Path, FakeLLMClient]:
    monkeypatch.chdir(tmp_path)
    slide = tmp_path / "slide.pdf"
    slide.write_bytes(b"fixture")
    vault = tmp_path / "vault"
    syllabus = vault / "00_Programa_Curso" / "ementa_estruturada.json"
    syllabus.parent.mkdir(parents=True)
    syllabus.write_text(StructuredSyllabus(modules=[module]).model_dump_json(), encoding="utf-8")
    mocker.patch(
        "cathedra.agents.graph.parse_slides",
        return_value=[SlideChunk(slide_number=1, title="Aula", raw_text="Aula gravada.")],
    )
    client = FakeLLMClient(
        structured_responses=[
            DraftResult(raw_draft="Conteúdo da aula."),
            AuditClaimsResponse(claims=[]),
            AuditClaimsResponse(claims=[]),
        ],
        text_responses=["Conteúdo da aula."],
    )
    mocker.patch("cathedra.cli.get_client", return_value=client)
    return slide, vault, client


def invoke(slide: Path, vault: Path, *extra: str) -> Result:
    return CliRunner().invoke(
        app,
        [
            "build-lesson",
            str(slide),
            "--discipline",
            "financas",
            "--lesson",
            "1",
            "--vault",
            str(vault),
            *extra,
        ],
    )


def test_transcript_lesson_number_is_optional_but_must_be_positive(
    transcript: VideoTranscript,
) -> None:
    assert VideoTranscript.model_validate(transcript.model_dump()).lesson_number is None
    for invalid in [0, -1, True]:
        with pytest.raises(ValidationError):
            VideoTranscript.model_validate({**transcript.model_dump(), "lesson_number": invalid})


@pytest.mark.parametrize("case", ["missing", "invalid", "discipline", "lesson"])
def test_explicit_invalid_transcript_blocks_before_llm(
    environment: tuple[Path, Path, FakeLLMClient],
    transcript: VideoTranscript,
    case: str,
) -> None:
    slide, vault, client = environment
    path = vault.parent / "explicit.json"
    if case == "invalid":
        path.write_text("{invalid", encoding="utf-8")
    elif case == "discipline":
        write_transcript(path, transcript.model_copy(update={"discipline_slug": "marketing"}), 1)
    elif case == "lesson":
        write_transcript(path, transcript, 2)
    result = invoke(slide, vault, "--transcript", str(path))
    assert result.exit_code != 0
    assert not client.calls
    assert not (vault / "01_Wiki_Disciplinas").exists()


def test_explicit_legacy_transcript_is_recorded_in_audit(
    environment: tuple[Path, Path, FakeLLMClient],
    transcript: VideoTranscript,
) -> None:
    slide, vault, _ = environment
    path = vault.parent / "legacy.json"
    write_transcript(path, transcript, None)
    result = invoke(slide, vault, "-t", "Finanças", "-T", str(path))
    assert result.exit_code == 0
    report_path = vault / "03_Auditoria_Factual" / "financas_Aula_01_audit.json"
    report = LessonAuditReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert report.source_transcript_filename == "video-aula.mp4"
    assert report.source_transcript_path == str(path.resolve())
    assert report.source_transcript_binding == "explicit"


def test_auto_selects_only_unique_numbered_transcript(
    environment: tuple[Path, Path, FakeLLMClient],
    transcript: VideoTranscript,
) -> None:
    slide, vault, _ = environment
    root = vault.parent / "data" / "raw" / "transcripts" / "financas"
    selected = root / "nome-arbitrario.json"
    write_transcript(selected, transcript, 1)
    write_transcript(root / "outra-aula.json", transcript, 2)
    result = invoke(slide, vault)
    assert result.exit_code == 0
    report_path = vault / "03_Auditoria_Factual" / "financas_Aula_01_audit.json"
    report = LessonAuditReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert report.source_transcript_path == str(selected.resolve())
    assert report.source_transcript_binding == "auto"


def test_auto_rejects_ambiguous_candidates(
    environment: tuple[Path, Path, FakeLLMClient],
    transcript: VideoTranscript,
) -> None:
    slide, vault, client = environment
    root = vault.parent / "data" / "raw" / "transcripts" / "financas"
    write_transcript(root / "primeiro.json", transcript, 1)
    write_transcript(root / "segundo.json", transcript, 1)
    result = invoke(slide, vault)
    assert result.exit_code != 0
    assert not client.calls
    assert not (vault / "01_Wiki_Disciplinas").exists()


def test_auto_does_not_guess_from_legacy_filename(
    environment: tuple[Path, Path, FakeLLMClient],
    transcript: VideoTranscript,
) -> None:
    slide, vault, _ = environment
    path = vault.parent / "data" / "raw" / "transcripts" / "financas" / "slide.json"
    write_transcript(path, transcript, None)
    result = invoke(slide, vault)
    assert result.exit_code == 0
    assert "transcrição" in result.output.lower()
    report_path = vault / "03_Auditoria_Factual" / "financas_Aula_01_audit.json"
    report = LessonAuditReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert report.source_transcript_path is None


def test_ingestion_rejects_mismatched_in_memory_transcript(
    environment: tuple[Path, Path, FakeLLMClient],
    module: SyllabusModule,
    transcript: VideoTranscript,
) -> None:
    slide, _, _ = environment
    wrong = transcript.model_copy(update={"discipline_slug": "marketing"})
    with pytest.raises(ValueError, match="disciplina"):
        ingestion_node(slide, module, 1, transcript=wrong)


def test_blocked_audit_records_transcript_provenance(
    environment: tuple[Path, Path, FakeLLMClient],
    transcript: VideoTranscript,
    mocker: MockerFixture,
) -> None:
    slide, vault, _ = environment
    path = vault.parent / "explicit.json"
    write_transcript(path, transcript, 1)
    client = FakeLLMClient(
        structured_responses=[
            DraftResult(raw_draft="Afirmação falsa."),
            AuditClaimsResponse(
                claims=[
                    ClaimAuditItem(
                        claim_id="C1",
                        quote="Afirmação falsa.",
                        category="technical",
                        verdict="false",
                        severity="S1",
                    )
                ]
            ),
        ]
    )
    mocker.patch("cathedra.cli.get_client", return_value=client)
    result = invoke(slide, vault, "--transcript", str(path))
    assert result.exit_code != 0
    report_path = vault / "03_Auditoria_Factual" / "pendentes" / "financas_Aula_01_audit.json"
    report = LessonAuditReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert report.source_transcript_filename == "video-aula.mp4"
    assert report.source_transcript_path == str(path.resolve())
    assert report.source_transcript_binding == "explicit"


def test_auto_rejects_matching_candidate_when_other_identity_is_unknown(
    environment: tuple[Path, Path, FakeLLMClient],
    transcript: VideoTranscript,
) -> None:
    slide, vault, client = environment
    root = vault.parent / "data" / "raw" / "transcripts" / "financas"
    write_transcript(root / "identificada.json", transcript, 1)
    write_transcript(root / "antiga.json", transcript, None)
    result = invoke(slide, vault)
    assert result.exit_code != 0
    assert "--transcript" in result.output
    assert not client.calls


def test_ingestion_revalidates_identity_for_automatic_selection(
    environment: tuple[Path, Path, FakeLLMClient],
    module: SyllabusModule,
    transcript: VideoTranscript,
) -> None:
    slide, vault, _ = environment
    path = vault.parent / "transcript.json"
    write_transcript(path, transcript, None)
    with pytest.raises(ValueError, match="número da aula"):
        ingestion_node(
            slide, module, 1, transcript_path=path, require_transcript_lesson_number=True
        )
    with pytest.raises(ValueError, match="não ambos"):
        ingestion_node(slide, module, 1, transcript=transcript, transcript_path=path)

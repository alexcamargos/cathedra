"""Checkpoint identity and preservation tests using only synthetic video bytes."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from mba_wiki.schemas import VideoTranscript
from mba_wiki.transcription.batch_runner import (
    BatchRunSummary,
    ProgressEvent,
    run_transcription_batch,
)
from mba_wiki.transcription.telemetry import TranscriptionLogger
from mba_wiki.transcription.transcriber import LectureTranscriber


class FakeTranscriber:
    def __init__(self, model_size: str = "large-v3", device: str = "cpu") -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = "int8"
        self.calls: list[str] = []

    def transcribe_file(
        self, audio_path: Path, discipline_slug: str, source_filename: str
    ) -> VideoTranscript:
        self.calls.append(source_filename)
        return VideoTranscript(
            source_filename=source_filename,
            discipline_slug=discipline_slug,
            duration_seconds=1,
            model_name=self.model_size,
            compute_type=self.compute_type,
            processed_at=datetime(2026, 1, 1, tzinfo=UTC),
            full_text_raw="fala",
            full_text_cleaned="fala",
        )


@pytest.fixture
def setup_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    videos = tmp_path / "videos"
    source = videos / "marketing" / "aula.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video ficticio inicial")
    output = tmp_path / "transcripts"
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"audio ficticio")

    @contextmanager
    def fake_extraction(path: Path) -> Iterator[Path]:
        yield wav

    monkeypatch.setattr("mba_wiki.transcription.batch_runner.extracted_audio", fake_extraction)
    return videos, output, source


def run_batch(
    tmp_path: Path,
    videos: Path,
    output: Path,
    transcriber: FakeTranscriber,
    force: bool = False,
    events: list[ProgressEvent] | None = None,
) -> BatchRunSummary:
    return run_transcription_batch(
        videos,
        output,
        transcriber=cast(LectureTranscriber, transcriber),
        force=force,
        logger=TranscriptionLogger(tmp_path / "logs"),
        progress_callback=events.append if events is not None else None,
    )


def read_transcript(output: Path) -> VideoTranscript:
    return VideoTranscript.model_validate_json(
        (output / "marketing" / "aula.json").read_text(encoding="utf-8")
    )


def test_checkpoint_records_identity_and_reuses_matching_output(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
) -> None:
    import hashlib

    videos, output, source = setup_batch
    client = FakeTranscriber()
    first = run_batch(tmp_path, videos, output, client)
    saved = read_transcript(output)
    assert first.videos_processed == 1
    assert saved.checkpoint is not None
    assert saved.checkpoint.source_relative_path == "marketing/aula.mp4"
    assert saved.checkpoint.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert saved.checkpoint.model_name == "large-v3"
    assert saved.checkpoint.device == "cpu"
    assert saved.checkpoint.compute_type == "int8"
    second = run_batch(tmp_path, videos, output, client)
    assert second.videos_skipped == 1
    assert client.calls == ["aula.mp4"]


@pytest.mark.parametrize("change", ["video", "model", "device", "compute", "engine"])
def test_changed_identity_reprocesses_with_preserved_previous_json(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
    change: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    videos, output, source = setup_batch
    client = FakeTranscriber()
    run_batch(tmp_path, videos, output, client)
    target = output / "marketing" / "aula.json"
    before = target.read_bytes()
    if change == "video":
        stat = source.stat()
        source.write_bytes(b"X" * stat.st_size)
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif change == "model":
        client.model_size = "medium"
    elif change == "device":
        client.device = "cuda"
    elif change == "compute":
        client.compute_type = "int8_float16"
    else:
        monkeypatch.setattr("mba_wiki.transcription.batch_runner.version", lambda _: "new-version")
    events: list[ProgressEvent] = []
    result = run_batch(tmp_path, videos, output, client, events=events)
    assert result.videos_processed == 1
    assert result.videos_skipped == 0
    backups = list((output / ".history" / "marketing").glob("*.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == before
    completed = next(event for event in events if event.phase == "completed")
    assert completed.backup_path == backups[0]
    assert read_transcript(output).checkpoint is not None


@pytest.mark.parametrize("invalid", [False, True])
def test_legacy_or_invalid_output_is_unverified_until_force_and_preserved(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
    invalid: bool,
) -> None:
    videos, output, _ = setup_batch
    target = output / "marketing" / "aula.json"
    target.parent.mkdir(parents=True)
    legacy = FakeTranscriber().transcribe_file(Path("dummy"), "marketing", "aula.mp4")
    previous = b"invalid json" if invalid else legacy.model_dump_json().encode()
    target.write_bytes(previous)
    events: list[ProgressEvent] = []
    client = FakeTranscriber()
    result = run_batch(tmp_path, videos, output, client, events=events)
    assert result.videos_skipped == 0
    assert result.videos_unverified == 1
    assert [event.phase for event in events] == ["unverified"]
    assert target.read_bytes() == previous
    assert client.calls == []
    forced = run_batch(tmp_path, videos, output, client, force=True)
    assert forced.videos_processed == 1
    backups = list((output / ".history" / "marketing").glob("*.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == previous


@pytest.mark.parametrize("field", ["source_filename", "discipline_slug"])
def test_force_never_replaces_legacy_json_identifying_another_source(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
    field: str,
) -> None:
    videos, output, _ = setup_batch
    target = output / "marketing" / "aula.json"
    target.parent.mkdir(parents=True)
    legacy = FakeTranscriber().transcribe_file(Path("dummy"), "marketing", "aula.mp4")
    value = "outro.mp4" if field == "source_filename" else "financas"
    previous = legacy.model_copy(update={field: value}).model_dump_json().encode()
    target.write_bytes(previous)
    client = FakeTranscriber()
    result = run_batch(tmp_path, videos, output, client, force=True)
    assert result.failed_videos
    assert target.read_bytes() == previous
    assert client.calls == []


@pytest.mark.parametrize("force", [False, True])
def test_destination_collisions_fail_before_writing_or_transcribing(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
    force: bool,
) -> None:
    videos, output, source = setup_batch
    source.with_suffix(".mkv").write_bytes(b"outro video")
    client = FakeTranscriber()
    target = output / "marketing" / "aula.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"anotacao anterior")
    with pytest.raises(ValueError, match="[Cc]olis"):
        run_batch(tmp_path, videos, output, client, force=force)
    assert client.calls == []
    assert target.read_bytes() == b"anotacao anterior"
    assert list(output.rglob("*.json")) == [target]


@pytest.mark.parametrize("force", [False, True])
def test_existing_checkpoint_for_different_source_is_never_overwritten(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
    force: bool,
) -> None:
    videos, output, source = setup_batch
    client = FakeTranscriber()
    run_batch(tmp_path, videos, output, client)
    target = output / "marketing" / "aula.json"
    previous = target.read_bytes()
    nested = videos / "Modulo" / "marketing"
    nested.mkdir(parents=True)
    source.rename(nested / source.name)
    result = run_batch(tmp_path, videos, output, client, force=force)
    assert result.failed_videos
    assert target.read_bytes() == previous
    assert client.calls == ["aula.mp4"]


def test_changed_video_during_transcription_does_not_publish(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    videos, output, source = setup_batch
    client = FakeTranscriber()
    run_batch(tmp_path, videos, output, client)
    target = output / "marketing" / "aula.json"
    before = target.read_bytes()
    original = client.transcribe_file

    def change_source(
        audio_path: Path, discipline_slug: str, source_filename: str
    ) -> VideoTranscript:
        result = original(audio_path, discipline_slug, source_filename)
        source.write_bytes(b"video modificado durante processamento")
        return result

    monkeypatch.setattr(client, "transcribe_file", change_source)
    result = run_batch(tmp_path, videos, output, client, force=True)
    assert result.failed_videos
    assert target.read_bytes() == before


def test_manual_lesson_number_survives_reprocessing_only_for_same_video(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
) -> None:
    videos, output, source = setup_batch
    client = FakeTranscriber()
    run_batch(tmp_path, videos, output, client)
    target = output / "marketing" / "aula.json"
    associated = read_transcript(output).model_copy(update={"lesson_number": 7})
    target.write_text(associated.model_dump_json(), encoding="utf-8")

    client.model_size = "medium"
    run_batch(tmp_path, videos, output, client)
    assert read_transcript(output).lesson_number == 7
    source.write_bytes(b"outro conteudo de video")
    run_batch(tmp_path, videos, output, client)
    assert read_transcript(output).lesson_number is None


def test_existing_json_edited_during_transcription_is_not_overwritten(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    videos, output, _ = setup_batch
    client = FakeTranscriber()
    run_batch(tmp_path, videos, output, client)
    target = output / "marketing" / "aula.json"
    original = client.transcribe_file
    edit = b"anotacao concorrente"

    def edit_target(
        audio_path: Path, discipline_slug: str, source_filename: str
    ) -> VideoTranscript:
        result = original(audio_path, discipline_slug, source_filename)
        target.write_bytes(edit)
        return result

    monkeypatch.setattr(client, "transcribe_file", edit_target)
    result = run_batch(tmp_path, videos, output, client, force=True)
    assert result.failed_videos
    assert target.read_bytes() == edit


def test_failed_replacement_keeps_original_and_backup(
    tmp_path: Path,
    setup_batch: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    videos, output, _ = setup_batch
    client = FakeTranscriber()
    run_batch(tmp_path, videos, output, client)
    target = output / "marketing" / "aula.json"
    previous = target.read_bytes()
    original_replace = os.replace

    def fail_transcript_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst) == target:
            raise OSError("Falha simulada na substituição")
        original_replace(src, dst)

    monkeypatch.setattr("mba_wiki.transcription.batch_runner.os.replace", fail_transcript_replace)
    result = run_batch(tmp_path, videos, output, client, force=True)
    assert result.failed_videos
    assert target.read_bytes() == previous
    backups = list((output / ".history" / "marketing").glob("*.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == previous
    assert not list(target.parent.glob("*.tmp"))


def test_legacy_migration_rejects_colliding_videos_without_moving_json(tmp_path: Path) -> None:
    from mba_wiki.transcription.batch_runner import migrate_legacy_transcripts

    videos = tmp_path / "videos" / "marketing"
    videos.mkdir(parents=True)
    (videos / "aula.mp4").write_bytes(b"video um")
    (videos / "aula.mkv").write_bytes(b"video dois")
    old = tmp_path / "transcripts" / "modulo-antigo" / "aula.json"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"transcricao existente")
    with pytest.raises(ValueError, match="[Cc]olis"):
        migrate_legacy_transcripts(old.parent.parent, videos_dir=videos.parent)
    assert old.read_bytes() == b"transcricao existente"

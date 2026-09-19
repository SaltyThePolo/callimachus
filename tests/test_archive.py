import json
from dataclasses import replace

from callimachus.archive import Archive
from callimachus.models import Meeting


def sample(**changes):
    return Meeting(
        **(
            dict(
                id="id/../one",
                title="../Review",
                start="2026-09-19T10:00:00Z",
                notes="Notes",
                summary="Summary",
                transcript="Hello",
            )
            | changes
        )
    )


def test_partial_is_explicit_and_identical_sync_does_not_rewrite(tmp_path):
    archive = Archive(tmp_path)
    first = archive.save(sample())
    assert json.loads((first.path / "metadata.json").read_text())["missing"] == ["recording"]
    assert (first.path / "notes.md").read_text() == "Notes"
    stamp = (first.path / "metadata.json").stat().st_mtime_ns
    second = archive.save(sample())
    assert second.path == first.path
    assert (second.path / "metadata.json").stat().st_mtime_ns == stamp
    assert first.path.is_relative_to(tmp_path)


def test_changed_notes_preserve_old_revision_and_publish_new_pointer(tmp_path):
    archive = Archive(tmp_path)
    first = archive.save(sample())
    second = archive.save(replace(sample(), notes="Revised"))
    assert first.path != second.path
    assert (first.path / "notes.md").read_text() == "Notes"
    assert json.loads(second.manifest.read_text())["revision"] == second.path.name


def test_recording_is_copied_and_makes_archive_complete(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"synthetic audio")
    result = Archive(tmp_path / "archive").save(sample(), audio)
    metadata = json.loads((result.path / "metadata.json").read_text())
    assert metadata["complete"] is True
    assert (result.path / "recording.wav").read_bytes() == audio.read_bytes()
    audio.write_bytes(b"changed source")
    assert (result.path / "recording.wav").read_bytes() == b"synthetic audio"


def test_integrity_damage_is_detected_and_not_published(tmp_path):
    archive = Archive(tmp_path)
    saved = archive.save(sample())
    (saved.path / "notes.md").write_text("corrupt")
    import pytest

    with pytest.raises(ValueError, match="integrity"):
        archive.save(sample())


def test_transcript_unavailable_does_not_create_fake_transcript(tmp_path):
    result = Archive(tmp_path).save(sample(transcript=None))
    assert not (result.path / "transcript.txt").exists()
    assert json.loads((result.path / "metadata.json").read_text())["missing"] == [
        "transcript",
        "recording",
    ]


def test_pending_summary_is_not_reported_complete(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"synthetic")
    result = Archive(tmp_path / "archive").save(sample(summary=""), audio)
    assert not result.complete
    assert "summary" in json.loads((result.path / "metadata.json").read_text())["missing"]


def test_empty_transcript_is_not_reported_complete(tmp_path):
    result = Archive(tmp_path).save(sample(transcript=""))
    assert "transcript" in json.loads((result.path / "metadata.json").read_text())["missing"]


def test_meeting_rejects_naive_time_and_invalid_text():
    import pytest

    with pytest.raises(ValueError, match="timezone"):
        sample(start="2026-09-19T10:00:00")
    with pytest.raises(ValueError, match="notes"):
        sample(notes={"bad": "type"})


def test_extra_file_breaks_immutable_revision_integrity(tmp_path):
    import pytest

    archive = Archive(tmp_path)
    saved = archive.save(sample())
    (saved.path / "unexpected.txt").write_text("not part of archive")
    with pytest.raises(ValueError, match="integrity"):
        archive.save(sample())

# Copyright (C) 2026 Mattia Riviera
# SPDX-License-Identifier: AGPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero
# General Public License for more details.

"""Explicit migration of legacy revision archives into the readable current-only layout."""

from test_cli import run

from callimachus.archive import Archive
from callimachus.models import Meeting

LEGACY = Meeting(
    id="legacy-one",
    title="Quarterly review",
    start="2026-06-01T09:00:00Z",
    notes="notes",
    summary="summary",
    transcript="words",
    modified_at="v1",
)


def legacy_archive(tmp_path, *meetings, audio=None):
    root = tmp_path / "archive"
    store = Archive(root)
    for meeting in meetings or [LEGACY]:
        store.save(meeting, audio)
    return root


def test_preview_lists_targets_and_changes_nothing(tmp_path):
    root = legacy_archive(tmp_path)
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*") if not p.name.startswith("."))
    result = run(tmp_path, "migrate")
    assert result.returncode == 0, result.stderr
    assert "2026-06-01 09-00 - Quarterly review" in result.stdout
    assert "legacy-one" not in result.stdout, "meeting IDs are not the way to refer to meetings"
    assert "preview" in result.stdout.lower() and "--apply" in result.stdout
    after = sorted(str(p.relative_to(root)) for p in root.rglob("*") if not p.name.startswith("."))
    assert after == before


def readable(tmp_path):
    return sorted(
        p.name
        for p in (tmp_path / "archive").iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def test_apply_converts_current_revision_is_rerunnable_and_keeps_legacy_until_cleanup(tmp_path):
    root = legacy_archive(
        tmp_path, LEGACY, LEGACY.model_copy(update=dict(notes="second revision", modified_at="v2"))
    )
    result = run(tmp_path, "migrate", "--apply")
    assert result.returncode == 0, result.stderr
    folder = tmp_path / "archive" / "2026-06-01 09-00 - Quarterly review"
    assert (folder / "notes.md").read_text() == "second revision", (
        "only the current revision is converted"
    )
    assert (folder / "transcript.md").read_text() == "words"
    assert (root / "meetings").is_dir(), "legacy data survives --apply"
    stamp = (folder / "notes.md").stat().st_mtime_ns
    again = run(tmp_path, "migrate", "--apply")
    assert again.returncode == 0 and (folder / "notes.md").stat().st_mtime_ns == stamp
    blocked = run(tmp_path, "sync", "--input", str(tmp_path / "none.json"))
    assert "migrate" in blocked.stderr, "sync still refuses the mixed directory"


def test_cleanup_removes_only_verified_directories_and_parks_the_rest(tmp_path):
    partial = Meeting(
        id="legacy-two",
        title="No transcript yet",
        start="2026-06-02T09:00:00Z",
        notes="n",
        summary="s",
        transcript=None,
    )
    with_audio = Meeting(
        id="legacy-three",
        title="Recorded",
        start="2026-06-03T09:00:00Z",
        notes="n",
        summary="s",
        transcript="t",
    )
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"synthetic")
    root = legacy_archive(tmp_path, LEGACY, partial)
    Archive(root).save(with_audio, audio)
    preview = run(tmp_path, "migrate")
    assert preview.returncode == 2 and "pending: transcript missing" in preview.stdout
    assert "keeps revisions/" in preview.stdout and "recording.wav" in preview.stdout
    assert run(tmp_path, "migrate", "--apply", "--cleanup").returncode == 2
    assert readable(tmp_path) == [
        "2026-06-01 09-00 - Quarterly review",
        "2026-06-03 09-00 - Recorded",
    ]
    assert not (root / "meetings").exists()
    parked = sorted(p.name for p in (root / ".legacy").iterdir())
    assert len(parked) == 2, "the partial meeting and the recorded one are kept, not deleted"
    assert list((root / ".legacy").rglob("recording.wav")), "attached audio is never deleted"
    assert (
        run(tmp_path, "sync", "--input", str(tmp_path / "none.json")).stderr.count("migrate") == 0
    )


def test_corrupt_legacy_entry_blocks_its_cleanup_and_the_rest_proceeds(tmp_path):
    other = Meeting(
        id="legacy-two",
        title="Fine",
        start="2026-06-02T09:00:00Z",
        notes="n",
        summary="s",
        transcript="t",
    )
    root = legacy_archive(tmp_path, LEGACY, other)
    victim = next(root.glob("meetings/*/revisions/*/notes.md"))
    victim.write_text("tampered")
    result = run(tmp_path, "migrate", "--apply", "--cleanup")
    assert result.returncode == 2 and "corrupt" in result.stdout
    assert len(readable(tmp_path)) == 1
    assert len(list((root / ".legacy").iterdir())) == 1, "the corrupt entry is parked intact"
    assert next((root / ".legacy").rglob("notes.md")).read_text() == "tampered"


def test_failed_verification_blocks_cleanup(tmp_path, monkeypatch):
    root = legacy_archive(tmp_path)
    run(tmp_path, "migrate", "--apply")
    # Something overwrote the converted file between conversion and cleanup.
    (tmp_path / "archive" / "2026-06-01 09-00 - Quarterly review" / "notes.md").write_text("edited")
    import callimachus.current as current

    monkeypatch.setattr(
        current.LocalStore, "write", lambda *a, **k: None
    )  # conversion cannot repair it
    from callimachus.config import Config

    env = tmp_path / "env"
    env.write_text(f"CALLIMACHUS_ARCHIVE_DIR={root}\nCALLIMACHUS_STATE_DIR={tmp_path / 'state'}\n")
    from callimachus.cli import current_archive
    from callimachus.migrate import run as migrate_run

    config = Config.load(env)
    assert migrate_run(root, current_archive(config), apply=True, cleanup=True) == 2
    assert (root / ".legacy").is_dir() and not (root / "meetings").exists()
    assert len(list((root / ".legacy").iterdir())) == 1, (
        "unverified conversion keeps the legacy copy"
    )


def test_drive_destination_is_migrated_from_the_local_staging_archive(tmp_path):
    from zoneinfo import ZoneInfo

    from test_drive import FakeDrive
    from test_drive_current import tree

    from callimachus.current import CurrentArchive
    from callimachus.drive import DriveStore
    from callimachus.migrate import run as migrate_run

    root = legacy_archive(tmp_path)
    service = FakeDrive()
    archive = CurrentArchive(
        DriveStore(service, tmp_path / "state"),
        tmp_path / "state" / "drive-registry.json",
        ZoneInfo("UTC"),
        False,
    )
    assert migrate_run(root, archive, apply=True, cleanup=False) == 0
    assert sorted(tree(service)["2026-06-01 09-00 - Quarterly review"]) == [
        "notes.md",
        "summary.md",
        "transcript.md",
    ]
    assert not list(root.glob("2026-*")), "Drive migration writes nothing readable locally"


def test_unmanifested_legacy_entry_with_a_recording_is_parked_not_deleted(tmp_path):
    root = legacy_archive(tmp_path)
    orphan = root / "meetings" / "orphan" / "revisions" / "rev"
    orphan.mkdir(parents=True)
    (orphan / "recording.m4a").write_bytes(b"synthetic audio")
    (root / "meetings" / "stray.txt").write_text("user file")
    result = run(tmp_path, "migrate", "--apply", "--cleanup")
    assert result.returncode == 2 and "no manifest" in result.stdout
    assert not (root / "meetings").exists()
    assert (
        root / ".legacy" / "orphan" / "revisions" / "rev" / "recording.m4a"
    ).read_bytes() == b"synthetic audio"
    assert (root / ".legacy" / "stray.txt").read_text() == "user file"

import json
import os
import shutil
import subprocess
import sys


def run(tmp_path, *args, **env):
    return subprocess.run(
        [sys.executable, "-m", "callimachus", *args],
        cwd=tmp_path,
        env=os.environ
        | {
            "CALLIMACHUS_ARCHIVE_DIR": str(tmp_path / "archive"),
            "CALLIMACHUS_STATE_DIR": str(tmp_path / "state"),
        }
        | env,
        capture_output=True,
        text=True,
    )


MEETING = {
    "id": "synthetic",
    "title": "Synthetic meeting",
    "start": "2026-09-19T10:00:00Z",
    "notes": "notes",
    "summary": "summary",
    "transcript": "words",
}


def fixture(tmp_path, *meetings, **changes):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(list(meetings) or [MEETING | changes]))
    return str(path)


def folders(tmp_path):
    return sorted(p.name for p in (tmp_path / "archive").iterdir() if p.is_dir())


def test_first_import_creates_readable_folder_with_three_markdown_files(tmp_path):
    result = run(tmp_path, "sync", "--input", fixture(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "imported=1" in result.stdout
    assert folders(tmp_path) == ["2026-09-19 10-00 - Synthetic meeting"]
    folder = tmp_path / "archive" / "2026-09-19 10-00 - Synthetic meeting"
    assert sorted(p.name for p in folder.iterdir()) == ["notes.md", "summary.md", "transcript.md"]
    assert (folder / "transcript.md").read_text() == "words"
    assert not list((tmp_path / "archive").rglob("*.json")), "no technical state in the archive"


def test_strict_mode_returns_failure_for_pending_text(tmp_path):
    complete = fixture(tmp_path)
    assert (
        run(tmp_path, "sync", "--input", complete, CALLIMACHUS_REQUIRE_COMPLETE="true").returncode
        == 0
    )
    pending = fixture(tmp_path, summary="")
    result = run(tmp_path, "sync", "--input", pending, CALLIMACHUS_REQUIRE_COMPLETE="true")
    assert result.returncode == 2
    assert "pending=1" in result.stdout


def test_invalid_configuration_fails_before_network(tmp_path):
    result = run(tmp_path, "sync", CALLIMACHUS_DESTINATION="typo")
    assert result.returncode == 1
    assert "CALLIMACHUS_DESTINATION" in result.stderr
    assert "Traceback" not in result.stderr


def test_missing_login_gives_actionable_error_without_tokens(tmp_path):
    result = run(tmp_path, "sync")
    assert result.returncode == 1
    assert "login wispr" in result.stderr


def test_invalid_date_and_bool_are_rejected(tmp_path):
    assert run(tmp_path, "sync", "--since", "yesterday").returncode == 1
    assert run(tmp_path, "doctor", CALLIMACHUS_REQUIRE_COMPLETE="tru").returncode == 1


def test_credentials_validation_errors_are_not_printed(capsys):
    from callimachus.cli import report_error

    report_error(ValueError("remote secret token must not appear"))
    assert "remote secret" not in capsys.readouterr().err


def test_watch_exits_on_strict_completeness_failure(tmp_path):
    result = run(
        tmp_path,
        "watch",
        "--input",
        fixture(tmp_path, transcript=None),
        CALLIMACHUS_REQUIRE_COMPLETE="true",
    )
    assert result.returncode == 2


def test_watch_releases_lock_between_passes(tmp_path):
    import time

    source = fixture(tmp_path)
    environment = os.environ | {
        "CALLIMACHUS_ARCHIVE_DIR": str(tmp_path / "archive"),
        "CALLIMACHUS_STATE_DIR": str(tmp_path / "state"),
        "CALLIMACHUS_DESTINATION": "local",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "callimachus", "watch", "--input", source],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while not list((tmp_path / "archive").rglob("notes.md")) and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(0.2)
        result = run(tmp_path, "doctor")  # takes the process lock: free between passes
        assert result.returncode == 0, result.stderr
    finally:
        process.terminate()
        process.communicate(timeout=5)


def test_repeated_import_rewrites_nothing(tmp_path):
    source = fixture(tmp_path)
    run(tmp_path, "sync", "--input", source)
    notes = tmp_path / "archive" / "2026-09-19 10-00 - Synthetic meeting" / "notes.md"
    stamp = notes.stat().st_mtime_ns
    again = run(tmp_path, "sync", "--input", source)
    assert again.returncode == 0 and "imported=1" in again.stdout
    assert notes.stat().st_mtime_ns == stamp
    assert folders(tmp_path) == ["2026-09-19 10-00 - Synthetic meeting"]


def test_source_edits_update_files_and_rename_folder(tmp_path):
    run(tmp_path, "sync", "--input", fixture(tmp_path))
    edited = fixture(
        tmp_path, title="Renamed: review/plan", notes="new notes", start="2026-09-19T11:30:00Z"
    )
    assert run(tmp_path, "sync", "--input", edited).returncode == 0
    assert folders(tmp_path) == ["2026-09-19 11-30 - Renamed review plan"]
    assert (tmp_path / "archive" / folders(tmp_path)[0] / "notes.md").read_text() == "new notes"


def test_timezone_is_configurable_validated_and_renames_on_change(tmp_path):
    source = fixture(tmp_path)
    assert (
        run(tmp_path, "sync", "--input", source, CALLIMACHUS_TIMEZONE="Europe/Rome").returncode == 0
    )
    assert folders(tmp_path) == ["2026-09-19 12-00 - Synthetic meeting"]
    assert (
        run(tmp_path, "sync", "--input", source, CALLIMACHUS_TIMEZONE="Asia/Tokyo").returncode == 0
    )
    assert folders(tmp_path) == ["2026-09-19 19-00 - Synthetic meeting"]
    bad = run(tmp_path, "sync", "--input", source, CALLIMACHUS_TIMEZONE="Mars/Olympus")
    assert bad.returncode == 1 and "CALLIMACHUS_TIMEZONE" in bad.stderr
    assert folders(tmp_path) == ["2026-09-19 19-00 - Synthetic meeting"], (
        "invalid timezone changes nothing"
    )


def test_same_name_meetings_get_numeric_suffixes_that_stay_stable(tmp_path):
    twin = MEETING | {"id": "other", "notes": "other notes"}
    source = fixture(tmp_path, MEETING, twin)
    run(tmp_path, "sync", "--input", source)
    expected = ["2026-09-19 10-00 - Synthetic meeting", "2026-09-19 10-00 - Synthetic meeting (2)"]
    assert folders(tmp_path) == expected
    run(
        tmp_path, "sync", "--input", fixture(tmp_path, twin, MEETING)
    )  # order changes, names do not
    assert folders(tmp_path) == expected
    assert (tmp_path / "archive" / expected[1] / "notes.md").read_text() == "other notes"


def test_incomplete_text_is_pending_and_preserves_current_files(tmp_path):
    pending = run(tmp_path, "sync", "--input", fixture(tmp_path, transcript=""))
    assert pending.returncode == 0 and "pending=1" in pending.stdout
    assert folders(tmp_path) == [], "no folder until summary and transcript exist"
    run(tmp_path, "sync", "--input", fixture(tmp_path, notes=""))  # empty personal notes are valid
    folder = tmp_path / "archive" / "2026-09-19 10-00 - Synthetic meeting"
    assert (folder / "notes.md").read_text() == "" and (
        folder / "transcript.md"
    ).read_text() == "words"
    run(tmp_path, "sync", "--input", fixture(tmp_path, title="Retitled", summary=""))
    assert folders(tmp_path) == ["2026-09-19 10-00 - Retitled"], (
        "rename applies while text is pending"
    )
    assert (tmp_path / "archive" / folders(tmp_path)[0] / "transcript.md").read_text() == "words"


def test_destination_deletions_stay_deleted_unless_restore_is_enabled(tmp_path):
    run(tmp_path, "sync", "--input", fixture(tmp_path))
    folder = tmp_path / "archive" / "2026-09-19 10-00 - Synthetic meeting"
    (folder / "transcript.md").unlink()
    edited = fixture(tmp_path, title="Edited", transcript="more words")
    run(tmp_path, "sync", "--input", edited)  # source edit + rename + restart
    folder = tmp_path / "archive" / "2026-09-19 10-00 - Edited"
    assert sorted(p.name for p in folder.iterdir()) == ["notes.md", "summary.md"]
    shutil.rmtree(folder)
    result = run(tmp_path, "sync", "--input", edited)
    assert "suppressed=1" in result.stdout and folders(tmp_path) == []
    restored = run(tmp_path, "sync", "--input", edited, CALLIMACHUS_RESTORE_DELETED="true")
    assert "imported=1" in restored.stdout
    assert (folder / "transcript.md").read_text() == "more words"
    (folder / "summary.md").unlink()
    run(
        tmp_path, "sync", "--input", edited
    )  # markers were cleared by restoration; new deletion recorded
    assert not (folder / "summary.md").exists()


def test_failed_first_creation_is_not_mistaken_for_deletion(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    registry = {
        "schema_version": 1,
        "meetings": {
            "synthetic": {
                "published": False,
                "deleted": [],
                "start": MEETING["start"],
                "title": MEETING["title"],
                "base": "2026-09-19 10-00 - Synthetic meeting",
                "folder": "2026-09-19 10-00 - Synthetic meeting",
            }
        },
    }
    (state / "registry.json").write_text(json.dumps(registry))
    run(tmp_path, "sync", "--input", fixture(tmp_path))
    assert folders(tmp_path) == ["2026-09-19 10-00 - Synthetic meeting"]


def test_legacy_revision_archive_requires_explicit_migration(tmp_path):
    legacy = tmp_path / "archive" / "meetings" / "abc"
    legacy.mkdir(parents=True)
    (legacy / "latest.json").write_text("{}")
    result = run(tmp_path, "sync", "--input", fixture(tmp_path))
    assert result.returncode == 1 and "migrate" in result.stderr
    visible = [p.name for p in (tmp_path / "archive").iterdir() if not p.name.startswith(".")]
    assert visible == ["meetings"], "nothing written next to the legacy archive"


def test_rename_survives_a_crash_before_the_registry_is_rewritten(tmp_path):
    run(tmp_path, "sync", "--input", fixture(tmp_path))
    old = tmp_path / "archive" / "2026-09-19 10-00 - Synthetic meeting"
    new = tmp_path / "archive" / "2026-09-19 10-00 - Renamed"
    (old / "notes.md").chmod(0o000)  # first write after the rename fails
    (old / "notes.md").unlink() if False else None
    failed = run(tmp_path, "sync", "--input", fixture(tmp_path, title="Renamed", notes="changed"))
    assert failed.returncode == 1 and new.is_dir() and not old.exists()
    (new / "notes.md").chmod(0o600)
    result = run(tmp_path, "sync", "--input", fixture(tmp_path, title="Renamed", notes="changed"))
    assert "imported=1" in result.stdout and folders(tmp_path) == ["2026-09-19 10-00 - Renamed"]
    assert (new / "notes.md").read_text() == "changed"


def test_source_deleted_meeting_is_retained_and_still_follows_timezone_changes(tmp_path):
    other = MEETING | {"id": "other", "title": "Kept"}
    run(tmp_path, "sync", "--input", fixture(tmp_path, MEETING, other))
    result = run(tmp_path, "sync", "--input", fixture(tmp_path), CALLIMACHUS_TIMEZONE="Europe/Rome")
    assert result.returncode == 0
    assert folders(tmp_path) == ["2026-09-19 12-00 - Kept", "2026-09-19 12-00 - Synthetic meeting"]
    assert (tmp_path / "archive" / "2026-09-19 12-00 - Kept" / "notes.md").read_text() == "notes"


def test_source_content_overwrites_local_edits(tmp_path):
    source = fixture(tmp_path)
    run(tmp_path, "sync", "--input", source)
    notes = tmp_path / "archive" / "2026-09-19 10-00 - Synthetic meeting" / "notes.md"
    notes.write_text("my local edit")
    run(tmp_path, "sync", "--input", source)
    assert notes.read_text() == "notes"


def test_pending_meeting_reserves_no_folder_name(tmp_path):
    complete_twin = MEETING | {"id": "other"}
    run(tmp_path, "sync", "--input", fixture(tmp_path, MEETING | {"summary": ""}, complete_twin))
    assert folders(tmp_path) == ["2026-09-19 10-00 - Synthetic meeting"]
    run(tmp_path, "sync", "--input", fixture(tmp_path, MEETING, complete_twin))
    assert folders(tmp_path) == [
        "2026-09-19 10-00 - Synthetic meeting",
        "2026-09-19 10-00 - Synthetic meeting (2)",
    ]


def test_unchanged_snapshots_are_skipped_and_edits_are_revisited(tmp_path):
    source = fixture(tmp_path, modified_at="v1")
    run(tmp_path, "sync", "--input", source)
    notes = tmp_path / "archive" / "2026-09-19 10-00 - Synthetic meeting" / "notes.md"
    stamp = notes.stat().st_mtime_ns
    again = run(tmp_path, "sync", "--input", source)
    assert "unchanged=1" in again.stdout and notes.stat().st_mtime_ns == stamp
    edited = run(
        tmp_path,
        "sync",
        "--input",
        fixture(tmp_path, modified_at="v2", notes="old meeting, new notes"),
    )
    assert "imported=1" in edited.stdout and notes.read_text() == "old meeting, new notes"


def test_failed_pass_then_success_is_visible_in_local_status(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("not json: secret words")
    failed = run(tmp_path, "sync", "--input", str(broken))
    status = json.loads((tmp_path / "state" / "status.json").read_text())
    assert failed.returncode == 1 and status["ok"] is False
    assert "secret words" not in json.dumps(status) and "secret words" not in failed.stderr
    doctor = run(tmp_path, "doctor")
    assert "last_pass=failed" in doctor.stdout
    good = run(tmp_path, "sync", "--input", fixture(tmp_path))
    status = json.loads((tmp_path / "state" / "status.json").read_text())
    assert (
        good.returncode == 0 and status["ok"] is True and status["summary"].startswith("imported=1")
    )


def test_second_writer_is_rejected_with_an_actionable_message(tmp_path):
    from filelock import FileLock

    (tmp_path / "state").mkdir()
    with FileLock(str(tmp_path / "state" / "process.lock")):
        result = run(tmp_path, "sync", "--input", fixture(tmp_path))
    assert result.returncode == 1 and "Callimachus process" in result.stderr

import json
import os
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


def fixture(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "synthetic",
                    "title": "Synthetic meeting",
                    "start": "2026-09-19T10:00:00Z",
                    "notes": "notes",
                    "summary": "summary",
                    "transcript": "words",
                }
            ]
        )
    )
    return str(path)


def test_offline_import_is_repeatable_and_audio_can_be_attached(tmp_path):
    source = fixture(tmp_path)
    first = run(tmp_path, "sync", "--input", source)
    assert first.returncode == 0, first.stderr
    assert "partial=1" in first.stdout
    second = run(tmp_path, "sync", "--input", source)
    assert second.returncode == 0
    assert len(list((tmp_path / "archive").rglob("metadata.json"))) == 1
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"synthetic bytes")
    assert run(tmp_path, "attach-audio", "synthetic", str(audio)).returncode == 0
    complete = run(tmp_path, "sync", "--input", source)
    assert complete.returncode == 0
    assert "partial=0" in complete.stdout
    assert len(list((tmp_path / "archive").rglob("metadata.json"))) == 2


def test_strict_mode_preserves_partial_archive_but_returns_failure(tmp_path):
    result = run(
        tmp_path, "sync", "--input", fixture(tmp_path), CALLIMACHUS_REQUIRE_COMPLETE="true"
    )
    assert result.returncode == 2
    assert list((tmp_path / "archive").rglob("metadata.json"))


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
        tmp_path, "watch", "--input", fixture(tmp_path), CALLIMACHUS_REQUIRE_COMPLETE="true"
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
        while (
            not list((tmp_path / "archive").rglob("metadata.json")) and time.monotonic() < deadline
        ):
            time.sleep(0.1)
        time.sleep(0.2)
        audio = tmp_path / "voice.wav"
        audio.write_bytes(b"synthetic")
        result = run(tmp_path, "attach-audio", "synthetic", str(audio))
        assert result.returncode == 0, result.stderr
    finally:
        process.terminate()
        process.communicate(timeout=5)

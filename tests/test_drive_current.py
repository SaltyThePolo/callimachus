"""Readable current-only archive delivered through the fake Drive boundary."""

import json
from zoneinfo import ZoneInfo

import pytest
from test_drive import FakeDrive

from callimachus.current import CurrentArchive
from callimachus.drive import FOLDER, DriveStore
from callimachus.models import Meeting

UTC = ZoneInfo("UTC")
MEETING = Meeting("meeting", "Demo", "2026-09-19T10:00:00Z", "notes", "summary", "words")


def archive(service, tmp_path, restore=False):
    store = DriveStore(service, tmp_path / "state")
    return CurrentArchive(store, tmp_path / "state" / "drive-registry.json", UTC, restore)


def tree(service):
    """{folder name: {file name: md5}} for every live meeting folder under the app root."""
    out = {}
    for item in service.items.values():
        if item.get("mimeType") == FOLDER and not item.get("trashed"):
            files = {
                f["name"]: f.get("md5Checksum")
                for f in service.items.values()
                if item["id"] in f.get("parents", [])
                and not f.get("trashed")
                and f.get("mimeType") != FOLDER
            }
            if files:
                out[item["name"]] = files
    return out


def test_first_sync_creates_readable_folder_and_repeat_sync_writes_nothing(tmp_path):
    service = FakeDrive()
    assert archive(service, tmp_path).publish(MEETING) == "imported"
    assert list(tree(service)) == ["2026-09-19 10-00 - Demo"]
    assert sorted(tree(service)["2026-09-19 10-00 - Demo"]) == [
        "notes.md",
        "summary.md",
        "transcript.md",
    ]
    roots = [i for i in service.items.values() if i["name"] == "Callimachus"]
    assert len(roots) == 1 and roots[0]["mimeType"] == FOLDER
    count, writes = len(service.items), list(service.writes)
    assert archive(service, tmp_path).publish(MEETING) == "imported"  # restart: new instances
    assert len(service.items) == count and service.writes == writes
    assert not list((tmp_path / "state").glob("**/*.md")), "no local content mirror"


def ids(service, folder):
    return {f["name"]: f["id"] for f in service.items.values() if folder in f.get("parents", [])}


def test_source_edits_update_contents_and_rename_folder_keeping_ids(tmp_path):
    service = FakeDrive()
    archive(service, tmp_path).publish(MEETING)
    folder_id = next(
        i["id"] for i in service.items.values() if i["name"] == "2026-09-19 10-00 - Demo"
    )
    before = ids(service, folder_id)
    edited = Meeting(
        "meeting", "Demo: renamed", "2026-09-19T10:00:00Z", "new notes", "summary", "words"
    )
    archive(service, tmp_path).publish(edited)
    assert list(tree(service)) == ["2026-09-19 10-00 - Demo renamed"]
    assert service.items[folder_id]["name"] == "2026-09-19 10-00 - Demo renamed"
    assert ids(service, folder_id) == before, "same objects, updated in place"
    assert service.writes[-2:] == ["2026-09-19 10-00 - Demo renamed", "notes.md"], (
        "only the name and the changed file"
    )


def test_failure_between_files_is_not_published_and_retry_converges(tmp_path):
    service = FakeDrive()
    service.fail_name = "summary.md"
    with pytest.raises(OSError):
        archive(service, tmp_path).publish(MEETING)
    registry = json.loads((tmp_path / "state" / "drive-registry.json").read_text())
    assert registry["meetings"]["meeting"]["published"] is False
    service.fail_name = None
    assert archive(service, tmp_path).publish(MEETING) == "imported"
    assert sorted(tree(service)["2026-09-19 10-00 - Demo"]) == [
        "notes.md",
        "summary.md",
        "transcript.md",
    ]
    assert service.writes.count("notes.md") == 1, (
        "the file written before the failure is not re-uploaded"
    )
    assert len(service.items) == 5  # root, folder, three files: no duplicates


def test_lost_create_response_and_lost_id_registry_do_not_duplicate_objects(tmp_path):
    service = FakeDrive()
    service.lose_response = True
    with pytest.raises(OSError):
        archive(service, tmp_path).publish(MEETING)
    archive(service, tmp_path).publish(MEETING)
    assert len(service.items) == 5
    (tmp_path / "state" / "drive-objects.json").unlink()  # local id registry lost
    archive(service, tmp_path).publish(MEETING)
    assert len(service.items) == 5, "objects recovered through appProperties, none recreated"


def test_trashed_file_stays_deleted_unless_restore_is_enabled(tmp_path):
    service = FakeDrive()
    archive(service, tmp_path).publish(MEETING)
    folder_id = next(
        i["id"] for i in service.items.values() if i["name"] == "2026-09-19 10-00 - Demo"
    )
    service.items[ids(service, folder_id)["transcript.md"]]["trashed"] = True
    edited = Meeting("meeting", "Demo", "2026-09-19T10:00:00Z", "notes", "summary", "more words")
    assert archive(service, tmp_path).publish(edited) == "imported"
    assert sorted(tree(service)["2026-09-19 10-00 - Demo"]) == ["notes.md", "summary.md"]
    service.items[folder_id]["trashed"] = True
    assert archive(service, tmp_path).publish(edited) == "suppressed"
    assert archive(service, tmp_path, restore=True).publish(edited) == "imported"
    assert sorted(tree(service)["2026-09-19 10-00 - Demo"]) == [
        "notes.md",
        "summary.md",
        "transcript.md",
    ]
    assert (
        len([i for i in service.items.values() if i["name"] == "2026-09-19 10-00 - Demo"]) == 2
    ), "the trashed folder is left alone; restoration creates a fresh one"


def test_manually_moved_or_renamed_folder_is_reported_not_repaired(tmp_path):
    service = FakeDrive()
    archive(service, tmp_path).publish(MEETING)
    folder = next(i for i in service.items.values() if i["name"] == "2026-09-19 10-00 - Demo")
    folder["name"] = "My own name"
    count = len(service.items)
    with pytest.raises(ValueError, match="manually"):
        archive(service, tmp_path).publish(MEETING)
    assert folder["name"] == "My own name" and len(service.items) == count


def test_existing_legacy_root_folder_is_reused(tmp_path):
    from callimachus.drive import DriveDestination

    service = FakeDrive()
    legacy_root = DriveDestination(
        service, tmp_path / "state"
    ).root()  # created by an earlier version
    archive(service, tmp_path).publish(MEETING)
    roots = [
        i for i in service.items.values() if i["name"] == "Callimachus" and i["mimeType"] == FOLDER
    ]
    assert [r["id"] for r in roots] == [legacy_root], "no second Callimachus folder"
    meeting_folder = next(
        i for i in service.items.values() if i["name"] == "2026-09-19 10-00 - Demo"
    )
    assert meeting_folder["parents"] == [legacy_root]

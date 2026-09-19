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

import hashlib
import re

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from callimachus.archive import Archive
from callimachus.drive import DriveDestination
from callimachus.models import Meeting


class Request:
    def __init__(self, fn):
        self.fn = fn

    def execute(self, **kwargs):
        return self.fn()

    def next_chunk(self, **kwargs):
        return None, self.fn()


class FakeDrive:
    """In-memory boundary for Google service; archive and uploader stay real."""

    def __init__(self):
        self.items = {}
        self.writes = []
        self.counter = 0
        self.fail_name = None
        self.lose_response = False

    def files(self):
        return self

    def generateIds(self, **kwargs):
        self.counter += 1
        return Request(lambda: {"ids": [f"remote-{self.counter}"]})

    def trashed(self, item):
        """Drive reports children of a trashed folder as trashed."""
        while item is not None:
            if item.get("trashed"):
                return True
            parents = [p for p in item.get("parents", []) if p in self.items]
            item = self.items[parents[0]] if parents else None
        return False

    def get(self, fileId, **kwargs):
        def run():
            if fileId not in self.items:
                raise HttpError(Response({"status": "404"}), b"missing")
            return self.items[fileId] | {"trashed": self.trashed(self.items[fileId])}

        return Request(run)

    def list(self, q="", **kwargs):
        def matches(item):
            parent = re.search(r"'([^']+)' in parents", q)
            key = re.search(r"key='callimachus_key' and value='([^']+)'", q)
            return (
                (not parent or parent.group(1) in item.get("parents", []))
                and (
                    not key or item.get("appProperties", {}).get("callimachus_key") == key.group(1)
                )
                and ("trashed = false" not in q or not self.trashed(item))
                and (
                    "mimeType = '" not in q
                    or item.get("mimeType") == re.search(r"mimeType = '([^']+)'", q).group(1)
                )
            )

        return Request(lambda: {"files": [i.copy() for i in self.items.values() if matches(i)]})

    def create(self, body, media_body=None, **kwargs):
        def run():
            if body["name"] == self.fail_name:
                raise OSError("synthetic disconnect")
            if body["id"] in self.items:
                raise HttpError(Response({"status": "409"}), b"exists")
            result = body.copy()
            if media_body:
                content = media_body.getbytes(0, media_body.size())
                result["md5Checksum"] = hashlib.md5(content).hexdigest()
            self.items[body["id"]] = result
            self.writes.append(body["name"])
            if self.lose_response:
                self.lose_response = False
                raise OSError("lost response after successful create")
            return result

        return Request(run)

    def update(self, fileId, body, media_body=None, **kwargs):
        def run():
            if self.items[fileId]["name"] == self.fail_name:
                raise OSError("synthetic disconnect")
            self.items[fileId].update(body)
            if media_body is not None:
                content = media_body.getbytes(0, media_body.size())
                self.items[fileId]["md5Checksum"] = hashlib.md5(content).hexdigest()
            self.writes.append(self.items[fileId]["name"])
            return self.items[fileId].copy()

        return Request(run)


def saved(tmp_path):
    return Archive(tmp_path / "archive").save(
        Meeting(
            id="meeting",
            title="Demo",
            start="2026-09-19T10:00:00Z",
            notes="notes",
            summary="summary",
            transcript="words",
        )
    )


def test_retry_reuses_files_and_manifest_is_last(tmp_path):
    service = FakeDrive()
    destination = DriveDestination(service, tmp_path / "state")
    archive = saved(tmp_path)
    destination.upload(archive)
    count = len(service.items)
    assert service.writes[-1] == "latest.json"
    writes = list(service.writes)
    DriveDestination(service, tmp_path / "state").upload(archive)
    assert len(service.items) == count
    assert service.writes == writes


def test_failed_artifact_never_publishes_manifest(tmp_path):
    service = FakeDrive()
    service.fail_name = "transcript.txt"
    destination = DriveDestination(service, tmp_path / "state")
    with pytest.raises(OSError):
        destination.upload(saved(tmp_path))
    assert "latest.json" not in service.writes
    service.fail_name = None
    destination.upload(saved(tmp_path))
    assert service.writes[-1] == "latest.json"


def test_lost_create_response_does_not_duplicate_root(tmp_path):
    service = FakeDrive()
    service.lose_response = True
    with pytest.raises(OSError):
        DriveDestination(service, tmp_path / "state").upload(saved(tmp_path))
    DriveDestination(service, tmp_path / "state").upload(saved(tmp_path))
    assert sum(x["name"] == "Callimachus" for x in service.items.values()) == 1


def test_staged_history_is_delivered_before_current_pointer(tmp_path):
    archive = Archive(tmp_path / "archive")
    original = Meeting(
        id="meeting",
        title="Demo",
        start="2026-09-19T10:00:00Z",
        notes="old",
        summary="summary",
        transcript="words",
    )
    first = archive.save(original)
    second = archive.save(original.model_copy(update=dict(notes="new")))
    service = FakeDrive()
    destination = DriveDestination(service, tmp_path / "state")
    destination.drain(archive)
    assert service.writes.count("notes.md") == 2
    assert service.writes.count("latest.json") == 1
    assert service.writes[-1] == "latest.json"
    assert first.path.name != second.path.name


def test_undeclared_file_is_not_uploaded(tmp_path):
    archive = saved(tmp_path)
    (archive.path / "private.txt").write_text("not part of the meeting")
    service = FakeDrive()
    with pytest.raises(ValueError, match="integrity"):
        DriveDestination(service, tmp_path / "state").upload(archive)
    assert not service.writes


def test_symlink_is_rejected_even_when_checksum_matches(tmp_path):
    archive = saved(tmp_path)
    target = tmp_path / "outside.txt"
    target.write_text("notes")
    (archive.path / "notes.md").unlink()
    (archive.path / "notes.md").symlink_to(target)
    service = FakeDrive()
    with pytest.raises(ValueError, match="integrity"):
        DriveDestination(service, tmp_path / "state").upload(archive)
    assert not service.writes

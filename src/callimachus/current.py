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

"""Readable current-only archive: one flat folder per meeting, three Markdown files.

Technical state lives in a private registry under the state directory, never in the
archive. The registry records deletion intent, so losing it is not a silent reset.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .errors import UserError
from .fs import atomic_write, canonical
from .models import Meeting

FILES = {"notes.md": "notes", "summary.md": "summary", "transcript.md": "transcript"}
WHOLE_FOLDER = "*"  # deletion marker for the whole meeting folder
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def ready(meeting: Meeting) -> bool:
    """Publishable text: nonempty summary and transcript; empty notes are valid."""
    return bool(meeting.summary.strip() and meeting.transcript and meeting.transcript.strip())


def folder_name(start: str, title: str, tz: ZoneInfo) -> str:
    stamp = datetime.fromisoformat(start).astimezone(tz).strftime("%Y-%m-%d %H-%M")
    clean = " ".join(_UNSAFE.sub(" ", title).split())[:80].rstrip(" .")
    return f"{stamp} - {clean or 'Untitled meeting'}"


class LocalStore:
    """Filesystem destination: one directory per meeting under the archive root."""

    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root

    def names(self) -> set[str]:
        return {p.name.casefold() for p in self.root.iterdir() if p.is_dir()}

    def present(self, meeting_id: str, folder: str) -> dict[str, str] | None:
        path = self.root / folder
        if not path.is_dir():
            return None
        return {n: md5((path / n).read_bytes()) for n in FILES if (path / n).is_file()}

    def rename(self, meeting_id: str, folder: str, new: str) -> None:
        if (
            self.root / folder
        ).is_dir():  # idempotent: a finished or user-deleted folder is left alone
            (self.root / folder).rename(self.root / new)

    def write(self, meeting_id: str, folder: str, name: str, data: bytes) -> None:
        atomic_write(self.root / folder / name, data)


class CurrentArchive:
    """Destination-independent policy: readiness, naming, renames, deletion intent."""

    def __init__(self, store, registry: Path, tz: ZoneInfo, restore: bool):
        self.store, self.tz, self.restore = store, tz, restore
        self.registry = registry
        data = (
            json.loads(registry.read_text())
            if registry.exists()
            else {"schema_version": 1, "meetings": {}}
        )
        if data.get("schema_version") != 1 or not isinstance(data.get("meetings"), dict):
            raise UserError("Unsupported registry format; restore it from backup")
        self.meetings: dict[str, dict] = data["meetings"]

    def _save(self) -> None:
        atomic_write(self.registry, canonical({"schema_version": 1, "meetings": self.meetings}))

    def _place(self, meeting_id: str, record: dict) -> str:
        """Keep the folder named after the current start/title/timezone; rename in the store.

        A rename is two-phase: the new name and the previous one are saved before the store
        moves anything, so a crash in between is finished on the next pass instead of being
        mistaken for a user deletion.
        """
        if "previous" in record:
            self.store.rename(meeting_id, record.pop("previous"), record["folder"])
            self._save()
        base = folder_name(record["start"], record["title"], self.tz)
        old = record.get("folder")
        if old and record.get("base") == base:
            return old
        # Conservative collision check: other registry folders and any stray directory.
        taken = {
            r["folder"].casefold()
            for k, r in self.meetings.items()
            if k != meeting_id and "folder" in r
        }
        taken |= self.store.names() - ({old.casefold()} if old else set())
        folder, n = base, 1
        while folder.casefold() in taken:
            n += 1
            folder = f"{base} ({n})"
        record.update(base=base, folder=folder)
        if old and old != folder:
            record["previous"] = old
            self._save()
            self.store.rename(meeting_id, old, folder)
            del record["previous"]
            self._save()
        return folder

    def reconcile(self) -> None:
        """Apply the configured timezone to every known meeting, even ones gone from the source."""
        for meeting_id, record in self.meetings.items():
            if "folder" in record:
                self._place(meeting_id, record)
        self._save()

    def unchanged(self, meeting_id: str, modified_at: str | None) -> bool:
        """True when the published snapshot is this one, so the source need not be fetched again."""
        record = self.meetings.get(meeting_id)
        return bool(
            record
            and record["published"]
            and modified_at is not None
            and record.get("modified_at") == modified_at
            and not (self.restore and record["deleted"])
        )

    def publish(self, meeting: Meeting) -> str:
        """Return imported, pending (source text incomplete) or suppressed (user deleted folder)."""
        record = self.meetings.setdefault(meeting.id, {"published": False, "deleted": []})
        record.update(start=meeting.start, title=meeting.title, modified_at=meeting.modified_at)
        if not ready(meeting):
            if "folder" in record:  # keep an existing folder named correctly, reserve no new name
                self._place(meeting.id, record)
            self._save()
            return "pending"
        folder = self._place(meeting.id, record)
        self._save()  # identity and name are known before the first write can fail
        present = self.store.present(meeting.id, folder)
        deleted = set(record["deleted"])
        if record["published"]:  # only a published folder can have been deleted by the user
            if present is None:
                deleted.add(WHOLE_FOLDER)
            else:
                deleted |= FILES.keys() - present.keys()
        if self.restore:
            deleted = set()  # cleared for good only once the writes below have succeeded
        if WHOLE_FOLDER in deleted:
            record["deleted"] = sorted(deleted)
            self._save()
            return "suppressed"
        for name, attr in FILES.items():
            if name in deleted:
                continue
            data = (getattr(meeting, attr) or "").encode()
            if (present or {}).get(name) != md5(data):
                self.store.write(meeting.id, folder, name, data)
        record.update(published=True, deleted=sorted(deleted))
        self._save()
        return "imported"

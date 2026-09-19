"""Readable current-only archive: one flat folder per meeting, three Markdown files.

Technical state lives in a private registry under the state directory, never in the
archive. The registry records deletion intent, so losing it is not a silent reset.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .archive import atomic_write, canonical
from .errors import UserError
from .models import Meeting

FILES = {"notes.md": "notes", "summary.md": "summary", "transcript.md": "transcript"}
WHOLE_FOLDER = "*"  # deletion marker for the whole meeting folder
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def ready(meeting: Meeting) -> bool:
    """Publishable text: nonempty summary and transcript; empty notes are valid."""
    return bool(meeting.summary.strip() and meeting.transcript and meeting.transcript.strip())


def folder_name(start: str, title: str, tz: ZoneInfo) -> str:
    stamp = datetime.fromisoformat(start).astimezone(tz).strftime("%Y-%m-%d %H-%M")
    clean = " ".join(_UNSAFE.sub(" ", title).split())[:80].rstrip(" .")
    return f"{stamp} - {clean or 'Untitled meeting'}"


class CurrentArchive:
    def __init__(self, root: Path, state: Path, tz: ZoneInfo, restore: bool):
        self.root, self.tz, self.restore = root, tz, restore
        if any(root.glob("meetings/*/latest.json")):
            raise UserError(
                "Legacy revision archive detected; run the migration before syncing here"
            )
        self.registry = state / "registry.json"
        data = (
            json.loads(self.registry.read_text())
            if self.registry.exists()
            else {"schema_version": 1, "meetings": {}}
        )
        if data.get("schema_version") != 1 or not isinstance(data.get("meetings"), dict):
            raise UserError("Unsupported registry format; restore it from backup")
        self.meetings: dict[str, dict] = data["meetings"]
        root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _save(self) -> None:
        atomic_write(self.registry, canonical({"schema_version": 1, "meetings": self.meetings}))

    def _place(self, meeting_id: str, record: dict) -> Path:
        """Keep the folder named after the current start/title/timezone; rename on disk."""
        base = folder_name(record["start"], record["title"], self.tz)
        old = record.get("folder")
        if old and record.get("base") == base:
            return self.root / old
        # Conservative collision check: other registry folders and any stray directory.
        taken = {
            r["folder"].casefold()
            for k, r in self.meetings.items()
            if k != meeting_id and "folder" in r
        }
        taken |= {p.name.casefold() for p in self.root.iterdir() if p.is_dir() and p.name != old}
        folder, n = base, 1
        while folder.casefold() in taken:
            n += 1
            folder = f"{base} ({n})"
        record.update(base=base, folder=folder)
        if old and old != folder and (self.root / old).is_dir():
            (self.root / old).rename(self.root / folder)
            self._save()  # a crash after the rename must not orphan the folder
        return self.root / folder

    def reconcile(self) -> None:
        """Apply the configured timezone to every known meeting, even ones gone from the source."""
        for meeting_id, record in self.meetings.items():
            self._place(meeting_id, record)
        self._save()

    def publish(self, meeting: Meeting) -> str:
        """Return imported, pending (source text incomplete) or suppressed (user deleted folder)."""
        record = self.meetings.setdefault(meeting.id, {"published": False, "deleted": []})
        record.update(start=meeting.start, title=meeting.title)
        if not ready(meeting):
            if "folder" in record:  # keep an existing folder named correctly, reserve no new name
                self._place(meeting.id, record)
            self._save()
            return "pending"
        path = self._place(meeting.id, record)
        deleted = set(record["deleted"])
        if record["published"]:  # only a published folder can have been deleted by the user
            if not path.is_dir():
                deleted.add(WHOLE_FOLDER)
            else:
                deleted |= {name for name in FILES if not (path / name).exists()}
        if WHOLE_FOLDER in deleted and not self.restore:
            record["deleted"] = sorted(deleted)
            self._save()
            return "suppressed"
        for name, attr in FILES.items():
            if name in deleted and not self.restore:
                continue
            data = (getattr(meeting, attr) or "").encode()
            if not (path / name).exists() or (path / name).read_bytes() != data:
                atomic_write(path / name, data)
        record.update(published=True, deleted=[] if self.restore else sorted(deleted))
        self._save()
        return "imported"

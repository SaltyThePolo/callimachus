"""Explicit migration of legacy revision archives into the readable current-only layout.

Preview changes nothing. --apply converts the current revision of every legacy meeting through
the normal publication policy (so naming, collisions and identity match a fresh import) and is
safe to rerun. --cleanup removes only legacy directories whose converted content was verified
and which hold nothing else; everything that remains is moved out of the way, never deleted.
"""

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .archive import validate_revision
from .current import FILES, CurrentArchive, folder_name, md5
from .errors import UserError
from .models import Meeting

LEGACY_TEXT = {"notes.md": "notes", "summary.md": "summary", "transcript.txt": "transcript"}
KNOWN = {"latest.json", "metadata.json", *LEGACY_TEXT}
PARKED = ".legacy"


@dataclass
class Item:
    path: Path
    meeting: Meeting | None = None
    status: str = ""
    extras: list[str] = field(default_factory=list)  # recordings and unknown files: never deleted

    @property
    def label(self) -> str:
        return self.meeting.title if self.meeting else f"legacy entry {self.path.name[:12]}"


def scan(root: Path) -> list[Item]:
    items = []
    for entry in sorted(p for p in root.glob("meetings/*") if p.is_dir()):
        item = Item(entry)
        manifest = entry / "latest.json"
        item.extras = sorted(
            str(p.relative_to(item.path))
            for p in item.path.rglob("*")
            if p.is_file() and (p.name not in KNOWN or p.name.startswith("recording."))
        )
        try:
            current = (
                item.path / "revisions" / str(json.loads(manifest.read_text()).get("revision"))
            )
            if not current.is_dir():
                raise UserError("current revision is missing")
            metadata = validate_revision(current)
            texts = {
                attr: (current / name).read_text(encoding="utf-8")
                if (current / name).exists()
                else None
                for name, attr in LEGACY_TEXT.items()
            }
            item.meeting = Meeting(
                id=metadata["id"],
                title=metadata["title"],
                start=metadata["start"],
                notes=texts["notes"] or "",
                summary=texts["summary"] or "",
                transcript=texts["transcript"],
                end=metadata.get("end"),
                modified_at=metadata.get("modified_at"),
                share_link=metadata.get("share_link"),
                attendees=metadata.get("attendees") or [],
            )
        except (ValueError, KeyError, OSError) as exc:
            item.status = f"corrupt: {exc}"
            items.append(item)
            continue
        missing = [
            n for n in ("summary", "transcript") if not (getattr(item.meeting, n) or "").strip()
        ]
        item.status = "ready" if not missing else "pending: " + " and ".join(missing) + " missing"
        items.append(item)
    return items


def verified(item: Item, archive: CurrentArchive) -> bool:
    """The destination holds exactly the legacy text for this meeting."""
    record = archive.meetings.get(item.meeting.id, {})
    present = (
        archive.store.present(item.meeting.id, record["folder"]) if "folder" in record else None
    )
    return present is not None and all(
        present.get(name) == md5((getattr(item.meeting, attr) or "").encode())
        for name, attr in FILES.items()
    )


def run(root: Path, archive: CurrentArchive, apply: bool, cleanup: bool) -> int:
    items = scan(root)
    if not items:
        print(f"No legacy revision archive found in {root}")
        return 0
    if apply:
        archive.reconcile()
    width = max(
        len(folder_name(i.meeting.start, i.meeting.title, archive.tz)) if i.meeting else 24
        for i in items
    )
    removable, kept = [], []
    print(f"Legacy archive: {root} ({len(items)} meetings)")
    for item in items:
        target = (
            folder_name(item.meeting.start, item.meeting.title, archive.tz)
            if item.meeting
            else item.label
        )
        blockers = [f"keeps {e}" for e in item.extras]
        if item.status != "ready":
            blockers.insert(0, item.status)
        elif apply:
            outcome = archive.publish(item.meeting)
            if outcome != "imported":
                blockers.insert(0, outcome)
            elif not verified(item, archive):
                blockers.insert(0, "conversion could not be verified")
        (kept if blockers else removable).append((item, blockers))
        note = "; ".join(blockers) if blockers else ("verified" if apply else "ready")
        print(f"  {target:<{width}}  {note}")
    if cleanup:
        for item, _ in removable:
            shutil.rmtree(item.path)
        leftovers = [i.path for i, _ in kept] + [
            p
            for p in (root / "meetings").iterdir()
            if not p.is_dir() and not p.name.startswith(".")
        ]
        if leftovers:  # never deleted: parked so sync can run and the user can review them
            (root / PARKED).mkdir(exist_ok=True)
            for path in leftovers:
                path.rename(root / PARKED / path.name)
        for stray in (root / "meetings").glob(".*"):
            stray.unlink()
        (root / "meetings").rmdir()  # fails loudly if anything unexpected is still there
        print(
            f"Removed {len(removable)} verified legacy meeting directories; {len(kept)} moved to {PARKED}/"
        )
    else:
        print(
            f"Cleanup would remove {len(removable)} legacy directories after verification and move {len(kept)} to {PARKED}/"
        )
        if not apply:
            print(
                "Preview only: nothing changed. Run `callimachus migrate --apply` to convert, then "
                "`callimachus migrate --apply --cleanup` to remove verified legacy directories."
            )
    return 2 if kept else 0  # something needs a look before the legacy copy can go

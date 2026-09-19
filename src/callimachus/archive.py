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

"""Immutable revisions; a manifest is the only mutable publication point."""

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import UserError
from .fs import atomic_write, canonical, checksum
from .models import Meeting


def validate_revision(path: Path) -> dict:
    entries = list(path.iterdir())
    if path.is_symlink() or any(p.is_symlink() or not p.is_file() for p in entries):
        raise UserError("Archive integrity check failed: unexpected file type")
    metadata = json.loads((path / "metadata.json").read_text())
    files = metadata.get("sha256")
    if not isinstance(files, dict) or {p.name for p in entries} != set(files) | {"metadata.json"}:
        raise UserError("Archive integrity check failed: unexpected or missing files")
    if hashlib.sha256(canonical(metadata)).hexdigest() != path.name:
        raise UserError("Archive metadata integrity check failed")
    for filename, digest in files.items():
        if Path(filename).name != filename or checksum(path / filename) != digest:
            raise UserError("Archive file integrity check failed")
    return metadata


@dataclass(frozen=True)
class SavedArchive:
    path: Path
    manifest: Path
    complete: bool
    key: str


class Archive:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def save(self, meeting: Meeting, audio: Path | None = None) -> SavedArchive:
        parent = self.root / "meetings" / meeting.key
        revisions = parent / "revisions"
        revisions.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix=".pending-", dir=revisions) as temporary:
            staged = Path(temporary)
            (staged / "notes.md").write_text(meeting.notes, encoding="utf-8")
            (staged / "summary.md").write_text(meeting.summary, encoding="utf-8")
            missing = [] if meeting.summary.strip() else ["summary"]
            if meeting.transcript is not None and meeting.transcript.strip():
                (staged / "transcript.txt").write_text(meeting.transcript, encoding="utf-8")
            else:
                missing.append("transcript")
            if audio is None:
                missing.append("recording")
            else:
                suffix = audio.suffix.lower()
                if suffix not in {".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".webm", ".flac", ".aac"}:
                    raise UserError("Unsupported recording extension")
                shutil.copyfile(audio, staged / f"recording{suffix}")
            files = {p.name: checksum(p) for p in sorted(staged.iterdir())}
            metadata = meeting.metadata() | {
                "schema_version": 1,
                "source": "wispr-flow",
                "complete": not missing,
                "missing": missing,
                "sha256": files,
            }
            (staged / "metadata.json").write_bytes(canonical(metadata))
            revision = hashlib.sha256(canonical(metadata)).hexdigest()
            destination = revisions / revision
            if destination.exists():
                validate_revision(destination)
                for p in staged.iterdir():
                    existing = destination / p.name
                    if not existing.is_file() or checksum(existing) != checksum(p):
                        raise UserError("Archive integrity check failed; restore damaged revision")
            else:
                for p in staged.iterdir():
                    p.chmod(0o600)
                    with p.open("rb") as stream:
                        os.fsync(stream.fileno())
                # Rename the whole revision before pointing readers at it.
                os.rename(staged, destination)
            manifest = parent / "latest.json"
            payload = canonical(
                {
                    "schema_version": 1,
                    "meeting_id": meeting.id,
                    "revision": revision,
                    "complete": not missing,
                }
            )
            if not manifest.exists() or manifest.read_bytes() != payload:
                atomic_write(manifest, payload)
            return SavedArchive(destination, manifest, not missing, meeting.key)

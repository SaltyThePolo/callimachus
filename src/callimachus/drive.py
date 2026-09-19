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

"""Direct Drive uploads with persisted generated IDs and manifest-last publication."""

import hashlib
import json
import mimetypes
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload

from .archive import Archive, SavedArchive, validate_revision
from .current import FILES
from .errors import UserError
from .fs import atomic_write, canonical, checksum
from .models import meeting_key

FOLDER = "application/vnd.google-apps.folder"
FIELDS = "id,name,mimeType,parents,appProperties,md5Checksum,trashed"


class DriveDestination:
    def __init__(self, service, state: Path, folder_id: str | None = None):
        self.files = service.files()
        self.registry_file = state / "drive-ids.json"
        self.registry = (
            json.loads(self.registry_file.read_text()) if self.registry_file.exists() else {}
        )
        self.folder_id = folder_id

    def _get(self, file_id):
        try:
            return self.files.get(fileId=file_id, fields=FIELDS, supportsAllDrives=True).execute(
                num_retries=3
            )
        except HttpError as exc:
            if exc.resp.status == 404:
                return None
            raise

    def _id(self, parent: str | None, name: str) -> tuple[str, str]:
        key = hashlib.sha256(canonical([parent, name])).hexdigest()
        if key not in self.registry:
            # Recover after local state loss without creating another object.
            parent_query = f" and '{parent}' in parents" if parent else ""
            matches = self.files.list(
                q=f"trashed = false and appProperties has {{ key='callimachus_key' and value='{key}' }}"
                + parent_query,
                spaces="drive",
                fields="files(id),nextPageToken",
                pageSize=100,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            ).execute(num_retries=3)
            if len(matches.get("files", [])) > 1 or matches.get("nextPageToken"):
                raise UserError("Duplicate Callimachus objects in Drive; resolve before syncing")
            if matches.get("files"):
                remote_id = matches["files"][0]["id"]
            else:
                remote_id = self.files.generateIds(count=1, space="drive", type="files").execute(
                    num_retries=3
                )["ids"][0]
            self.registry[key] = remote_id
            atomic_write(self.registry_file, canonical(self.registry))
        return self.registry[key], key

    @staticmethod
    def _check(existing: dict, key: str, parent: str | None) -> None:
        if (
            existing.get("trashed")
            or existing.get("appProperties", {}).get("callimachus_key") != key
        ):
            raise UserError("Drive archive object was removed or replaced; resolve before syncing")
        if parent and parent not in existing.get("parents", []):
            raise UserError("Drive archive object was moved; restore it before syncing")

    def _folder(self, parent: str | None, name: str) -> str:
        """Get or create an archive folder; folders are never modified."""
        remote_id, key = self._id(parent, name)
        existing = self._get(remote_id)
        if existing:
            self._check(existing, key, parent)
            if existing.get("mimeType") != FOLDER:
                raise UserError("Expected an archive folder in Drive")
            return remote_id
        body = {
            "id": remote_id,
            "name": name,
            "mimeType": FOLDER,
            "appProperties": {"callimachus_key": key},
        }
        if parent:
            body["parents"] = [parent]
        self.files.create(body=body, fields="id", supportsAllDrives=True).execute(num_retries=3)
        return remote_id

    def _file(self, parent: str, name: str, path: Path, *, mutable: bool = False) -> str:
        """Upload unless Drive holds identical content; only a mutable file may be replaced."""
        remote_id, key = self._id(parent, name)
        existing = self._get(remote_id)
        if existing:
            self._check(existing, key, parent)
            with path.open("rb") as stream:
                md5 = hashlib.file_digest(stream, "md5").hexdigest()
            if existing.get("md5Checksum") == md5:
                return remote_id
            if not mutable:
                raise UserError("Drive archive integrity mismatch; restore the remote revision")
        body = {"name": name, "appProperties": {"callimachus_key": key, "sha256": checksum(path)}}
        mimetype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        media = MediaFileUpload(
            str(path), mimetype=mimetype, resumable=True, chunksize=8 * 1024 * 1024
        )
        if existing:
            request = self.files.update(
                fileId=remote_id, body=body, media_body=media, fields="id", supportsAllDrives=True
            )
        else:
            body |= {"id": remote_id, "parents": [parent]}
            request = self.files.create(
                body=body, media_body=media, fields="id", supportsAllDrives=True
            )
        result = None
        while result is None:
            _, result = request.next_chunk(num_retries=3)
        return remote_id

    def root(self) -> str:
        if self.folder_id:
            if not all(c.isalnum() or c in "_-" for c in self.folder_id):
                raise UserError("Drive folder must be an ID, not a URL")
            folder = self._get(self.folder_id)
            if not folder or folder.get("mimeType") != FOLDER or folder.get("trashed"):
                raise UserError("Drive folder is unavailable to this OAuth app")
            return self.folder_id
        return self._folder(None, "Callimachus")

    def upload(self, saved: SavedArchive, publish=True) -> str:
        metadata = validate_revision(saved.path)
        if meeting_key(metadata["id"]) != saved.key:
            raise UserError("Archive meeting identity integrity mismatch")
        if publish:
            latest = json.loads(saved.manifest.read_text())
            if (
                latest.get("revision") != saved.path.name
                or latest.get("meeting_id") != metadata["id"]
            ):
                raise UserError("Archive manifest integrity mismatch")
        root = self.root()
        meetings = self._folder(root, "meetings")
        meeting = self._folder(meetings, saved.key)
        revisions = self._folder(meeting, "revisions")
        revision = self._folder(revisions, saved.path.name)
        for path in sorted(saved.path.iterdir()):
            self._file(revision, path.name, path)
        if publish:
            self._file(meeting, "latest.json", saved.manifest, mutable=True)
        return f"https://drive.google.com/drive/folders/{meeting}"

    def drain(self, archive: Archive) -> None:
        """Replay local history independently of the live source; publish current last."""
        for manifest in sorted(archive.root.glob("meetings/*/latest.json")):
            latest = json.loads(manifest.read_text())
            revision = latest.get("revision", "")
            if len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
                raise UserError("Invalid local archive manifest")
            current = manifest.parent / "revisions" / revision
            if not current.is_dir():
                raise UserError("Current local revision is missing")
            paths = sorted(
                p for p in current.parent.iterdir() if p.is_dir() and not p.name.startswith(".")
            )
            paths = [p for p in paths if p != current] + [current]
            for path in paths:
                metadata = validate_revision(path)
                saved = SavedArchive(path, manifest, metadata["complete"], manifest.parent.name)
                self.upload(saved, publish=path == current)


class DriveStore:
    """Readable current-only destination on Drive: stable pre-allocated IDs, in-memory uploads.

    Identity lives in a private id registry keyed by sha256(meeting id + object name); every
    object also carries that key in appProperties so it can be recovered after registry loss.
    """

    def __init__(self, service, state: Path, folder_id: str | None = None):
        self.files = service.files()
        self.ids_file = state / "drive-objects.json"
        self.ids = json.loads(self.ids_file.read_text()) if self.ids_file.exists() else {}
        self.folder_id = folder_id
        self._root: str | None = None

    # -- transport primitives -------------------------------------------------------------
    def _get(self, file_id: str | None) -> dict | None:
        if file_id is None:
            return None
        try:
            item = self.files.get(fileId=file_id, fields=FIELDS, supportsAllDrives=True).execute(
                num_retries=3
            )
        except HttpError as exc:
            if exc.resp.status == 404:
                return None
            raise
        return item

    def _list(self, query: str) -> list[dict]:
        found, token = [], None
        while True:
            page = self.files.list(
                q=query,
                spaces="drive",
                fields=f"files({FIELDS}),nextPageToken",
                pageSize=1000,
                pageToken=token,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            ).execute(num_retries=3)
            found += page.get("files", [])
            token = page.get("nextPageToken")
            if not token:
                return found

    def _id(self, key: str) -> str:
        """Stable Drive ID for an app-owned object; persisted before any create call."""
        if key not in self.ids:
            # Recover after local state loss without creating another object.
            matches = self._list(
                f"trashed = false and appProperties has {{ key='callimachus_key' and value='{key}' }}"
            )
            if len(matches) > 1:
                raise UserError("Duplicate Callimachus objects in Drive; resolve before syncing")
            self.ids[key] = (
                matches[0]["id"]
                if matches
                else self.files.generateIds(count=1, space="drive", type="files").execute(
                    num_retries=3
                )["ids"][0]
            )
            atomic_write(self.ids_file, canonical(self.ids))
        return self.ids[key]

    def _ensure(self, key: str, parent: str, name: str, data: bytes | None) -> tuple[dict, bool]:
        """Create or update one object under parent; return (item, created).

        An ambiguous earlier create converges here because the ID was allocated first. A
        trashed object keeps its ID forever, so recreation needs a fresh one.
        """
        file_id = self._id(key)
        existing = self._get(file_id)
        if existing and existing.get("trashed"):
            del self.ids[key]
            file_id, existing = self._id(key), None
        body: dict = {"name": name, "appProperties": {"callimachus_key": key}}
        media = None
        if data is None:
            body["mimeType"] = FOLDER
        else:
            media = MediaInMemoryUpload(data, mimetype="text/markdown", resumable=False)
        if existing:
            if parent != "root" and parent not in existing.get("parents", []):
                raise UserError(
                    "Drive archive object was moved manually; this is unsupported, move it back"
                )
            same_content = (
                data is None or existing.get("md5Checksum") == hashlib.md5(data).hexdigest()
            )
            if same_content and existing.get("name") == name:
                return existing, False
            request = self.files.update(
                fileId=file_id,
                body=body,
                media_body=None if same_content else media,
                fields=FIELDS,
                supportsAllDrives=True,
            )
            return request.execute(num_retries=3), False
        body |= {"id": file_id, "parents": [parent]}
        request = self.files.create(
            body=body, media_body=media, fields=FIELDS, supportsAllDrives=True
        )
        return request.execute(num_retries=3), True

    @staticmethod
    def _key(meeting_id: str, name: str) -> str:
        return hashlib.sha256(f"{meeting_id}/{name}".encode()).hexdigest()

    # -- root ---------------------------------------------------------------------------------
    def root(self) -> str:
        if self._root:
            return self._root
        if self.folder_id:
            if not all(c.isalnum() or c in "_-" for c in self.folder_id):
                raise UserError("Drive folder must be an ID, not a URL")
            folder = self._get(self.folder_id)
            if not folder or folder.get("trashed") or folder.get("mimeType") != FOLDER:
                raise UserError("Drive folder is unavailable to this OAuth app")
            self._root = self.folder_id
        else:
            self._adopt_legacy_root()
            self._root = self._ensure(self._key("", "root"), "root", "Callimachus", None)[0]["id"]
        return self._root

    def _adopt_legacy_root(self) -> None:
        """Reuse the Callimachus folder an earlier version created instead of making a second one."""
        key, legacy_file = self._key("", "root"), self.ids_file.with_name("drive-ids.json")
        if key in self.ids or not legacy_file.exists():
            return
        legacy_key = hashlib.sha256(canonical([None, "Callimachus"])).hexdigest()
        folder = self._get(json.loads(legacy_file.read_text()).get(legacy_key))
        if folder and not folder.get("trashed") and folder.get("mimeType") == FOLDER:
            self.ids[key] = folder["id"]
            atomic_write(self.ids_file, canonical(self.ids))

    # -- store interface used by CurrentArchive ------------------------------------------------
    def names(self) -> set[str]:
        return {
            f["name"].casefold()
            for f in self._list(
                f"'{self.root()}' in parents and mimeType = '{FOLDER}' and trashed = false"
            )
        }

    def _folder(self, meeting_id: str, folder: str) -> dict | None:
        """The live meeting folder, found by its stable key even if the local id table was lost."""
        item = self._get(self._id(self._key(meeting_id, "folder")))
        if item is None or item.get("trashed"):
            return None
        if item.get("name") != folder or self.root() not in item.get("parents", []):
            raise UserError(
                f"Drive folder for a meeting was renamed or moved manually ({item.get('name')!r}); "
                "this is unsupported, restore it or delete it"
            )
        return item

    def present(self, meeting_id: str, folder: str) -> dict[str, str] | None:
        item = self._folder(meeting_id, folder)
        if item is None:
            return None
        by_key = {
            f.get("appProperties", {}).get("callimachus_key"): f
            for f in self._list(f"'{item['id']}' in parents and trashed = false")
        }
        return {
            name: by_key[self._key(meeting_id, name)]["md5Checksum"]
            for name in FILES
            if self._key(meeting_id, name) in by_key
        }

    def rename(self, meeting_id: str, folder: str, new: str) -> None:
        self._ensure(self._key(meeting_id, "folder"), self.root(), new, None)

    def write(self, meeting_id: str, folder: str, name: str, data: bytes) -> None:
        parent, created = self._ensure(self._key(meeting_id, "folder"), self.root(), folder, None)
        if created:  # a fresh folder (first creation or restoration) gets fresh file objects
            for stale in FILES:
                self.ids.pop(self._key(meeting_id, stale), None)
        self._ensure(self._key(meeting_id, name), parent["id"], name, data)

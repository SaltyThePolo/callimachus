"""Direct Drive uploads with persisted generated IDs and manifest-last publication."""

import hashlib
import json
import mimetypes
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .archive import Archive, SavedArchive, atomic_write, canonical, checksum, validate_revision
from .errors import UserError

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

    def _put(self, parent: str | None, name: str, path: Path | None = None) -> str:
        remote_id, key = self._id(parent, name)
        existing = self._get(remote_id)
        props = {"callimachus_key": key}
        if path is not None:
            props["sha256"] = checksum(path)
        if existing:
            if (
                existing.get("trashed")
                or existing.get("appProperties", {}).get("callimachus_key") != key
            ):
                raise UserError(
                    "Drive archive object was removed or replaced; resolve before syncing"
                )
            if parent and parent not in existing.get("parents", []):
                raise UserError("Drive archive object was moved; restore it before syncing")
            if path is None:
                if existing.get("mimeType") != FOLDER:
                    raise UserError("Expected an archive folder in Drive")
                return remote_id
            with path.open("rb") as stream:
                md5 = hashlib.file_digest(stream, "md5").hexdigest()
            if existing.get("md5Checksum") == md5:
                return remote_id
            # Immutable revisions are never overwritten if changed externally.
            if name != "latest.json":
                raise UserError("Drive archive integrity mismatch; restore the remote revision")
        body = {"name": name, "appProperties": props}
        media = None
        if path is None:
            body["mimeType"] = FOLDER
        else:
            media = MediaFileUpload(
                str(path),
                mimetype=mimetypes.guess_type(name)[0] or "application/octet-stream",
                resumable=True,
                chunksize=8 * 1024 * 1024,
            )
        if existing:
            request = self.files.update(
                fileId=remote_id, body=body, media_body=media, fields="id", supportsAllDrives=True
            )
        else:
            body["id"] = remote_id
            if parent:
                body["parents"] = [parent]
            kwargs = {"body": body, "fields": "id", "supportsAllDrives": True}
            if media:
                kwargs["media_body"] = media
            request = self.files.create(**kwargs)
        if media:
            result = None
            while result is None:
                _, result = request.next_chunk(num_retries=3)
        else:
            request.execute(num_retries=3)
        return remote_id

    def root(self) -> str:
        if self.folder_id:
            if not all(c.isalnum() or c in "_-" for c in self.folder_id):
                raise UserError("Drive folder must be an ID, not a URL")
            folder = self._get(self.folder_id)
            if not folder or folder.get("mimeType") != FOLDER or folder.get("trashed"):
                raise UserError("Drive folder is unavailable to this OAuth app")
            return self.folder_id
        return self._put(None, "Callimachus")

    def upload(self, saved: SavedArchive, publish=True) -> str:
        metadata = validate_revision(saved.path)
        if hashlib.sha256(metadata["id"].encode()).hexdigest() != saved.key:
            raise UserError("Archive meeting identity integrity mismatch")
        if publish:
            latest = json.loads(saved.manifest.read_text())
            if (
                latest.get("revision") != saved.path.name
                or latest.get("meeting_id") != metadata["id"]
            ):
                raise UserError("Archive manifest integrity mismatch")
        root = self.root()
        meetings = self._put(root, "meetings")
        meeting = self._put(meetings, saved.key)
        revisions = self._put(meeting, "revisions")
        revision = self._put(revisions, saved.path.name)
        for path in sorted(saved.path.iterdir()):
            self._put(revision, path.name, path)
        if publish:
            self._put(meeting, "latest.json", saved.manifest)
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

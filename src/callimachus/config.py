import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import UserError


@dataclass(frozen=True)
class Config:
    archive: Path
    state: Path
    destination: str
    interval: int
    require_complete: bool
    google_client: Path | None
    google_folder: str | None

    @classmethod
    def load(cls, env_file: Path):
        load_dotenv(env_file, override=False)
        destination = os.getenv("CALLIMACHUS_DESTINATION", "local")
        if destination not in {"local", "drive"}:
            raise UserError("CALLIMACHUS_DESTINATION must be local or drive")
        try:
            interval = int(os.getenv("CALLIMACHUS_POLL_INTERVAL", "300"))
        except ValueError:
            raise UserError("CALLIMACHUS_POLL_INTERVAL must be an integer") from None
        if interval < 60:
            raise UserError("CALLIMACHUS_POLL_INTERVAL must be at least 60 seconds")
        required = os.getenv("CALLIMACHUS_REQUIRE_COMPLETE", "false").lower()
        if required not in {"true", "false"}:
            raise UserError("CALLIMACHUS_REQUIRE_COMPLETE must be true or false")
        client = os.getenv("CALLIMACHUS_GOOGLE_CLIENT_SECRET_FILE", "")
        return cls(
            archive=Path(os.getenv("CALLIMACHUS_ARCHIVE_DIR", "./archive")).expanduser().resolve(),
            state=Path(os.getenv("CALLIMACHUS_STATE_DIR", "./.callimachus")).expanduser().resolve(),
            destination=destination,
            interval=interval,
            require_complete=required == "true",
            google_client=Path(client).expanduser().resolve() if client else None,
            google_folder=os.getenv("CALLIMACHUS_GOOGLE_DRIVE_FOLDER_ID") or None,
        )

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

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

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
    timezone: ZoneInfo
    restore: bool
    oauth_bind: str

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
        timezone = os.getenv("CALLIMACHUS_TIMEZONE", "UTC")
        try:
            zone = ZoneInfo(timezone)
        except (KeyError, ValueError, OSError):
            raise UserError("CALLIMACHUS_TIMEZONE must be an IANA timezone name") from None
        client = os.getenv("CALLIMACHUS_GOOGLE_CLIENT_SECRET_FILE", "")
        return cls(
            archive=Path(os.getenv("CALLIMACHUS_ARCHIVE_DIR", "./archive")).expanduser().resolve(),
            state=Path(os.getenv("CALLIMACHUS_STATE_DIR", "./.callimachus")).expanduser().resolve(),
            destination=destination,
            interval=interval,
            require_complete=_flag("CALLIMACHUS_REQUIRE_COMPLETE"),
            google_client=Path(client).expanduser().resolve() if client else None,
            google_folder=os.getenv("CALLIMACHUS_GOOGLE_DRIVE_FOLDER_ID") or None,
            timezone=zone,
            restore=_flag("CALLIMACHUS_RESTORE_DELETED"),
            oauth_bind=os.getenv("CALLIMACHUS_OAUTH_BIND", "127.0.0.1"),
        )


def _flag(name: str) -> bool:
    value = os.getenv(name, "false").lower()
    if value not in {"true", "false"}:
        raise UserError(f"{name} must be true or false")
    return value == "true"

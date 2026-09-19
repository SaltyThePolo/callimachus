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

from dataclasses import asdict, dataclass, field
from datetime import datetime
from hashlib import sha256

from .errors import UserError


def meeting_key(meeting_id: str) -> str:
    return sha256(meeting_id.encode()).hexdigest()


@dataclass(frozen=True)
class Meeting:
    id: str
    title: str
    start: str
    notes: str
    summary: str
    transcript: str | None
    end: str | None = None
    modified_at: str | None = None
    share_link: str | None = None
    attendees: list = field(default_factory=list)

    def __post_init__(self):
        for name in ("id", "title", "start", "notes", "summary"):
            if not isinstance(getattr(self, name), str):
                raise UserError(f"Meeting {name} must be a string")
        if not self.id:
            raise UserError("Meeting id cannot be empty")
        if self.transcript is not None and not isinstance(self.transcript, str):
            raise UserError("Meeting transcript must be text or null")
        try:
            if datetime.fromisoformat(self.start).tzinfo is None:
                raise ValueError()
        except ValueError:
            raise UserError("Meeting start must be an ISO datetime with timezone") from None

    @property
    def key(self) -> str:
        return meeting_key(self.id)

    def metadata(self) -> dict:
        return {
            k: v for k, v in asdict(self).items() if k not in {"notes", "summary", "transcript"}
        }

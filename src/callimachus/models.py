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

from hashlib import sha256

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


def meeting_key(meeting_id: str) -> str:
    return sha256(meeting_id.encode()).hexdigest()


class Meeting(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str
    start: AwareDatetime
    notes: str
    summary: str
    transcript: str | None
    end: AwareDatetime | None = None
    modified_at: str | None = None  # opaque Wispr version token, compared for equality only
    share_link: str | None = None
    attendees: list[str] = []

    @property
    def key(self) -> str:
        return meeting_key(self.id)

    def metadata(self) -> dict:
        return self.model_dump(mode="json", exclude={"notes", "summary", "transcript"})

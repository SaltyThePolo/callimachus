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

from datetime import datetime
from zoneinfo import ZoneInfo

from callimachus.current import folder_name

UTC = ZoneInfo("UTC")


def test_folder_name_uses_configured_timezone():
    assert (
        folder_name(datetime.fromisoformat("2026-09-19T23:30:00Z"), "Late", ZoneInfo("Asia/Tokyo"))
        == "2026-09-20 08-30 - Late"
    )


def test_folder_name_normalizes_unsafe_characters_and_trailing_dots():
    name = folder_name(
        datetime.fromisoformat("2026-09-19T10:00:00Z"), ' Q3: "plan" <draft>/v2 ... ', UTC
    )
    assert name == "2026-09-19 10-00 - Q3 plan draft v2"


def test_folder_name_bounds_length_and_falls_back_for_empty_title():
    long = folder_name(datetime.fromisoformat("2026-09-19T10:00:00Z"), "x" * 500, UTC)
    assert len(long) == len("2026-09-19 10-00 - ") + 80
    assert (
        folder_name(datetime.fromisoformat("2026-09-19T10:00:00Z"), " ??? ", UTC)
        == "2026-09-19 10-00 - Untitled meeting"
    )


def test_interrupted_rename_is_finished_on_the_next_pass_not_treated_as_deletion(tmp_path):
    from callimachus.current import CurrentArchive, LocalStore
    from callimachus.models import Meeting

    class Crashy(LocalStore):
        def rename(self, meeting_id, folder, new):
            raise OSError("crash before the store moved the folder")

    meeting = Meeting(
        id="m", title="First", start="2026-09-19T10:00:00Z", notes="n", summary="s", transcript="t"
    )
    registry = tmp_path / "registry.json"
    CurrentArchive(LocalStore(tmp_path / "a"), registry, UTC, False).publish(meeting)
    renamed = Meeting(
        id="m", title="Second", start="2026-09-19T10:00:00Z", notes="n", summary="s", transcript="t"
    )
    try:
        CurrentArchive(Crashy(tmp_path / "a"), registry, UTC, False).publish(renamed)
    except OSError:
        pass
    outcome = CurrentArchive(LocalStore(tmp_path / "a"), registry, UTC, False).publish(renamed)
    assert outcome == "imported"
    assert sorted(p.name for p in (tmp_path / "a").iterdir() if p.is_dir()) == [
        "2026-09-19 10-00 - Second"
    ]

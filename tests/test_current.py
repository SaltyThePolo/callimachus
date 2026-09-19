from zoneinfo import ZoneInfo

from callimachus.current import folder_name

UTC = ZoneInfo("UTC")


def test_folder_name_uses_configured_timezone():
    assert (
        folder_name("2026-09-19T23:30:00Z", "Late", ZoneInfo("Asia/Tokyo"))
        == "2026-09-20 08-30 - Late"
    )


def test_folder_name_normalizes_unsafe_characters_and_trailing_dots():
    name = folder_name("2026-09-19T10:00:00Z", ' Q3: "plan" <draft>/v2 ... ', UTC)
    assert name == "2026-09-19 10-00 - Q3 plan draft v2"


def test_folder_name_bounds_length_and_falls_back_for_empty_title():
    long = folder_name("2026-09-19T10:00:00Z", "x" * 500, UTC)
    assert len(long) == len("2026-09-19 10-00 - ") + 80
    assert (
        folder_name("2026-09-19T10:00:00Z", " ??? ", UTC) == "2026-09-19 10-00 - Untitled meeting"
    )

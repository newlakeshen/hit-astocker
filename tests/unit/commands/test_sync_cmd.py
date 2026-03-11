from datetime import date

from hit_astocker.commands.sync_cmd import _resolve_sync_range


def test_resolve_sync_range_supports_trailing_years_from_explicit_end():
    start_date, end_date = _resolve_sync_range("20260310", None, None, 6)

    assert start_date == date(2020, 3, 10)
    assert end_date == date(2026, 3, 10)

"""Date utility functions.

All trading-day logic delegates to the global TradeCalendar singleton
(initialised via ``init_trade_calendar(conn)``).  The old weekday-only
heuristic has been removed so that A-share holidays are handled correctly.
"""

from datetime import date, datetime, timedelta

from hit_astocker.config.constants import TUSHARE_DATE_FMT


def to_tushare_date(d: date) -> str:
    return d.strftime(TUSHARE_DATE_FMT)


def from_tushare_date(s: str) -> date:
    return datetime.strptime(s, TUSHARE_DATE_FMT).date()


def shift_years(d: date, years: int) -> date:
    """Shift a date by whole years, clamping Feb 29 to Feb 28 when needed."""
    target_year = d.year + years
    try:
        return d.replace(year=target_year)
    except ValueError:
        return d.replace(year=target_year, day=28)


def date_range(start: date, end: date) -> list[date]:
    """Generate list of calendar dates from start to end (inclusive)."""
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def get_previous_trading_day(d: date, trading_days: set[date] | None = None) -> date | None:
    """Get the previous trading day before *d*.

    If *trading_days* is provided explicitly it is used (legacy compat);
    otherwise the global TradeCalendar is consulted.
    """
    if trading_days:
        # Legacy path: caller supplied an explicit set
        from bisect import bisect_left
        sorted_days = sorted(trading_days)
        idx = bisect_left(sorted_days, d)
        return sorted_days[idx - 1] if idx > 0 else None

    from hit_astocker.utils.trade_calendar import get_trade_calendar
    return get_trade_calendar().get_previous(d)


def get_next_trading_day(d: date) -> date | None:
    """Get the next trading day after *d*."""
    from hit_astocker.utils.trade_calendar import get_trade_calendar
    return get_trade_calendar().get_next(d)


def get_recent_trading_days(
    d: date,
    count: int,
    trading_days: set[date] | None = None,
) -> list[date]:
    """Get the most recent N trading days before *d* (newest first)."""
    if trading_days:
        from bisect import bisect_left
        sorted_days = sorted(trading_days)
        idx = bisect_left(sorted_days, d)
        start = max(0, idx - count)
        return list(reversed(sorted_days[start:idx]))

    from hit_astocker.utils.trade_calendar import get_trade_calendar
    return get_trade_calendar().get_recent(d, count)


def get_trading_days_between(start: date, end: date) -> list[date]:
    """Return sorted trading days in [start, end] inclusive."""
    from hit_astocker.utils.trade_calendar import get_trade_calendar
    return get_trade_calendar().get_trading_days_between(start, end)


def count_trading_days_between(start: date, end: date) -> int:
    """Count trading days in (start, end] — after start, up to and including end.

    Used for event decay: "how many trading days have passed since event date".
    Falls back to calendar days if trade calendar not initialised.
    """
    try:
        from hit_astocker.utils.trade_calendar import get_trade_calendar
        return get_trade_calendar().count_trading_days_between(start, end)
    except RuntimeError:
        return (end - start).days

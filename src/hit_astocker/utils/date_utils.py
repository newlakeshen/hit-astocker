"""Date utility functions."""

from datetime import date, datetime, timedelta

from hit_astocker.config.constants import TUSHARE_DATE_FMT


def to_tushare_date(d: date) -> str:
    return d.strftime(TUSHARE_DATE_FMT)


def from_tushare_date(s: str) -> date:
    return datetime.strptime(s, TUSHARE_DATE_FMT).date()


def date_range(start: date, end: date) -> list[date]:
    """Generate list of dates from start to end (inclusive)."""
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def get_previous_trading_day(d: date, trading_days: set[date] | None = None) -> date | None:
    """Get the previous trading day. Uses simple weekday heuristic if no calendar provided."""
    if trading_days:
        candidates = sorted([td for td in trading_days if td < d], reverse=True)
        return candidates[0] if candidates else None
    # Simple heuristic: skip weekends
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:  # Saturday=5, Sunday=6
        prev -= timedelta(days=1)
    return prev


def get_recent_trading_days(d: date, count: int, trading_days: set[date] | None = None) -> list[date]:
    """Get the most recent N trading days before d."""
    result = []
    current = d
    for _ in range(count * 2):  # Over-iterate to handle weekends/holidays
        prev = get_previous_trading_day(current, trading_days)
        if prev is None:
            break
        result.append(prev)
        current = prev
        if len(result) >= count:
            break
    return result

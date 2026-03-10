"""Trading calendar backed by the trade_cal table (SSE real calendar).

Provides a module-level singleton so every module can access the same
calendar without passing it around.

Usage::

    from hit_astocker.utils.trade_calendar import init_trade_calendar, get_trade_calendar

    # Once, early in the process (after ensure_schema):
    init_trade_calendar(conn)

    # Anywhere else:
    cal = get_trade_calendar()
    cal.get_previous(some_date)
"""

import bisect
import logging
import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_calendar: "TradeCalendar | None" = None


def init_trade_calendar(conn: sqlite3.Connection) -> "TradeCalendar":
    """Initialise (or re-initialise) the global trade calendar from DB."""
    global _calendar  # noqa: PLW0603
    cal = TradeCalendar()
    cal.load(conn)
    _calendar = cal
    return cal


def get_trade_calendar() -> "TradeCalendar":
    """Return the global calendar.  Raises if not yet initialised."""
    if _calendar is None:
        raise RuntimeError(
            "TradeCalendar not initialised. Call init_trade_calendar(conn) first."
        )
    return _calendar


# ---------------------------------------------------------------------------
# TradeCalendar
# ---------------------------------------------------------------------------
class TradeCalendar:
    """Trading calendar that caches trading days in a sorted list for
    O(log n) previous / next lookups via bisect.
    """

    def __init__(self):
        self._sorted_days: list[date] = []
        self._day_set: set[date] = set()

    # -- loaders -------------------------------------------------------------

    def load(self, conn: sqlite3.Connection) -> None:
        """Load from trade_cal table; fall back to limit_list_d if empty."""
        self._load_from_trade_cal(conn)
        if not self._sorted_days:
            self._load_from_limit_list(conn)
        if self._sorted_days:
            logger.info(
                "TradeCalendar loaded: %d trading days (%s ~ %s)",
                len(self._sorted_days),
                self._sorted_days[0],
                self._sorted_days[-1],
            )
        else:
            logger.warning("TradeCalendar: no trading days loaded — heuristic mode")

    def _load_from_trade_cal(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT cal_date FROM trade_cal WHERE is_open = 1 ORDER BY cal_date"
        ).fetchall()
        self._set_days([datetime.strptime(r[0], TUSHARE_DATE_FMT).date() for r in rows])

    def _load_from_limit_list(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT DISTINCT trade_date FROM limit_list_d ORDER BY trade_date"
        ).fetchall()
        self._set_days([datetime.strptime(r[0], TUSHARE_DATE_FMT).date() for r in rows])

    def _set_days(self, days: list[date]) -> None:
        self._sorted_days = sorted(days)
        self._day_set = set(self._sorted_days)

    # -- queries -------------------------------------------------------------

    def is_trading_day(self, d: date) -> bool:
        if not self._day_set:
            return d.weekday() < 5
        return d in self._day_set

    def get_previous(self, d: date) -> date | None:
        """Return the trading day immediately before *d*."""
        if not self._sorted_days:
            return None
        idx = bisect.bisect_left(self._sorted_days, d)
        if idx > 0:
            return self._sorted_days[idx - 1]
        return None

    def get_next(self, d: date) -> date | None:
        """Return the trading day immediately after *d*."""
        if not self._sorted_days:
            return None
        idx = bisect.bisect_right(self._sorted_days, d)
        if idx < len(self._sorted_days):
            return self._sorted_days[idx]
        return None

    def get_latest(self) -> date | None:
        return self._sorted_days[-1] if self._sorted_days else None

    def get_recent(self, d: date, count: int) -> list[date]:
        """Get N most recent trading days strictly before *d* (newest first)."""
        if not self._sorted_days:
            return []
        idx = bisect.bisect_left(self._sorted_days, d)
        start = max(0, idx - count)
        return list(reversed(self._sorted_days[start:idx]))

    def get_trading_days_between(self, start: date, end: date) -> list[date]:
        """Return sorted trading days in [start, end] inclusive."""
        if not self._sorted_days:
            return []
        lo = bisect.bisect_left(self._sorted_days, start)
        hi = bisect.bisect_right(self._sorted_days, end)
        return self._sorted_days[lo:hi]

    @property
    def trading_days(self) -> set[date]:
        return self._day_set

"""Trading calendar using Tushare trade_cal API."""

from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT


class TradeCalendar:
    """Trading calendar that caches trading days in memory."""

    def __init__(self):
        self._trading_days: set[date] = set()

    def load_from_tushare(self, pro, start_date: str = "20200101", end_date: str = "20271231"):
        df = pro.trade_cal(
            exchange="SSE",
            start_date=start_date,
            end_date=end_date,
            fields="cal_date,is_open",
        )
        self._trading_days = {
            datetime.strptime(row["cal_date"], TUSHARE_DATE_FMT).date()
            for _, row in df.iterrows()
            if row["is_open"] == 1
        }

    def load_from_db(self, conn):
        """Load distinct trade dates from existing data as fallback."""
        sql = "SELECT DISTINCT trade_date FROM limit_list_d ORDER BY trade_date"
        rows = conn.execute(sql).fetchall()
        self._trading_days = {
            datetime.strptime(r[0], TUSHARE_DATE_FMT).date() for r in rows
        }

    def is_trading_day(self, d: date) -> bool:
        if not self._trading_days:
            # Fallback: weekday heuristic
            return d.weekday() < 5
        return d in self._trading_days

    def get_previous(self, d: date) -> date | None:
        candidates = sorted([td for td in self._trading_days if td < d], reverse=True)
        return candidates[0] if candidates else None

    def get_next(self, d: date) -> date | None:
        candidates = sorted([td for td in self._trading_days if td > d])
        return candidates[0] if candidates else None

    def get_latest(self) -> date | None:
        return max(self._trading_days) if self._trading_days else None

    def get_recent(self, d: date, count: int) -> list[date]:
        """Get N most recent trading days before d."""
        candidates = sorted([td for td in self._trading_days if td < d], reverse=True)
        return candidates[:count]

    @property
    def trading_days(self) -> set[date]:
        return self._trading_days

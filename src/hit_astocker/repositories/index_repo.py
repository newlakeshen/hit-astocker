"""Repository for market index daily data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.index_data import IndexDaily
from hit_astocker.repositories.base import BaseRepository


class IndexDailyRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "index_daily")

    def find_by_date_and_code(self, trade_date: date, ts_code: str) -> IndexDaily | None:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_code_and_date(ts_code, date_str)
        return self._to_model(rows[0]) if rows else None

    def find_records_by_date(self, trade_date: date) -> list[IndexDaily]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_recent(self, ts_code: str, trade_date: date, count: int = 20) -> list[IndexDaily]:
        """Get the most recent N bars for an index up to and including trade_date."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT * FROM index_daily
            WHERE ts_code = ? AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, (ts_code, date_str, count)).fetchall()
        return [self._to_model(r) for r in reversed(rows)]  # oldest first

    @staticmethod
    def _to_model(row: sqlite3.Row) -> IndexDaily:
        return IndexDaily(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            open=row["open"] or 0.0,
            high=row["high"] or 0.0,
            low=row["low"] or 0.0,
            close=row["close"] or 0.0,
            pre_close=row["pre_close"] or 0.0,
            pct_chg=row["pct_chg"] or 0.0,
            vol=row["vol"] or 0.0,
            amount=row["amount"] or 0.0,
        )

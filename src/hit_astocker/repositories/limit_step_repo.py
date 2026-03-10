"""Repository for limit_step (consecutive board ladder) data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.limit_step import ConsecutiveLimitRecord
from hit_astocker.repositories.base import BaseRepository


class LimitStepRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "limit_step")

    def find_records_by_date(self, trade_date: date) -> list[ConsecutiveLimitRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_by_height(self, trade_date: date, min_height: int = 2) -> list[ConsecutiveLimitRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT * FROM limit_step WHERE trade_date = ? AND nums >= ? ORDER BY nums DESC"
        rows = self._conn.execute(sql, (date_str, min_height)).fetchall()
        return [self._to_model(r) for r in rows]

    def get_max_height(self, trade_date: date) -> int:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT MAX(nums) FROM limit_step WHERE trade_date = ?"
        row = self._conn.execute(sql, (date_str,)).fetchone()
        return row[0] if row[0] is not None else 0

    def get_height_counts(self, trade_date: date) -> dict[int, int]:
        """Get count of stocks at each consecutive board height."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT nums, COUNT(*) as cnt
            FROM limit_step WHERE trade_date = ?
            GROUP BY nums ORDER BY nums DESC
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return {r["nums"]: r["cnt"] for r in rows}

    def get_stock_heights(self, trade_date: date) -> dict[str, int]:
        """Get {ts_code: height} mapping for a date."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT ts_code, nums FROM limit_step WHERE trade_date = ?"
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return {r["ts_code"]: r["nums"] for r in rows}

    @staticmethod
    def _to_model(row: sqlite3.Row) -> ConsecutiveLimitRecord:
        return ConsecutiveLimitRecord(
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            nums=row["nums"] or 0,
        )

"""Repository for limit_list_d data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.limit_data import LimitDirection, LimitRecord
from hit_astocker.repositories.base import BaseRepository


class LimitListRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "limit_list_d")

    def find_records_by_date(self, trade_date: date) -> list[LimitRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_records_by_type(
        self, trade_date: date, limit_type: LimitDirection
    ) -> list[LimitRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = 'SELECT * FROM limit_list_d WHERE trade_date = ? AND "limit" = ?'
        rows = self._conn.execute(sql, (date_str, limit_type.value)).fetchall()
        return [self._to_model(r) for r in rows]

    def count_by_type(self, trade_date: date) -> dict[str, int]:
        """Count limit-up, limit-down, broken for a date."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT "limit", COUNT(*) as cnt
            FROM limit_list_d
            WHERE trade_date = ?
            GROUP BY "limit"
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        result = {"U": 0, "D": 0, "Z": 0}
        for r in rows:
            result[r["limit"]] = r["cnt"]
        return result

    def find_first_board_stocks(self, trade_date: date) -> list[LimitRecord]:
        """Find stocks with their first limit-up (limit_times == 1)."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT * FROM limit_list_d
            WHERE trade_date = ? AND "limit" = 'U' AND limit_times = 1
            ORDER BY first_time ASC
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return [self._to_model(r) for r in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> LimitRecord:
        return LimitRecord(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            industry=row["industry"] or "",
            close=row["close"] or 0.0,
            pct_chg=row["pct_chg"] or 0.0,
            amount=row["amount"] or 0.0,
            limit_amount=row["limit_amount"] or 0.0,
            float_mv=row["float_mv"] or 0.0,
            total_mv=row["total_mv"] or 0.0,
            turnover_ratio=row["turnover_ratio"] or 0.0,
            fd_amount=row["fd_amount"] or 0.0,
            first_time=row["first_time"] or "",
            last_time=row["last_time"] or "",
            open_times=row["open_times"] or 0,
            up_stat=row["up_stat"] or "",
            limit_times=row["limit_times"] or 0,
            limit=LimitDirection(row["limit"]),
        )

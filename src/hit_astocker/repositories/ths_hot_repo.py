"""Repository for 同花顺热股排名 data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.ths_hot_data import ThsHotRecord
from hit_astocker.repositories.base import BaseRepository


class ThsHotRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "ths_hot")

    def find_records_by_date(self, trade_date: date, market: str = "热股") -> list[ThsHotRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT * FROM ths_hot WHERE trade_date = ? AND market = ? ORDER BY rank"
        rows = self._conn.execute(sql, (date_str, market)).fetchall()
        return [self._to_model(r) for r in rows]

    def find_by_code(self, ts_code: str, trade_date: date) -> ThsHotRecord | None:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT * FROM ths_hot WHERE ts_code = ? AND trade_date = ? AND market = '热股' LIMIT 1"
        rows = self._conn.execute(sql, (ts_code, date_str)).fetchall()
        return self._to_model(rows[0]) if rows else None

    def find_recent_appearances(self, ts_code: str, trade_date: date, days: int = 5) -> int:
        """Count how many times a stock appeared in hot list in recent N trading days."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT COUNT(DISTINCT trade_date) FROM ths_hot
            WHERE ts_code = ? AND trade_date <= ? AND market = '热股'
            ORDER BY trade_date DESC LIMIT ?
        """
        # Use subquery for proper date range
        sql = """
            SELECT COUNT(*) FROM (
                SELECT DISTINCT trade_date FROM ths_hot
                WHERE ts_code = ? AND trade_date <= ? AND market = '热股'
                ORDER BY trade_date DESC LIMIT ?
            )
        """
        row = self._conn.execute(sql, (ts_code, date_str, days)).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _to_model(row: sqlite3.Row) -> ThsHotRecord:
        return ThsHotRecord(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            ts_name=row["ts_name"] or "",
            data_type=row["data_type"] or "",
            current_price=row["current_price"] or 0.0,
            rank=row["rank"] or 0,
            pct_change=row["pct_change"] or 0.0,
            rank_reason=row["rank_reason"] or "",
            rank_time=row["rank_time"] or "",
            concept=row["concept"] or "",
            hot=row["hot"] or 0,
            market=row["market"] or "热股",
        )

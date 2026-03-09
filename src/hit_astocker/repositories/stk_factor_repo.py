"""Repository for 个股技术因子 data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.stk_factor_data import StockFactorRecord
from hit_astocker.repositories.base import BaseRepository


class StockFactorRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "stk_factor_pro")

    def find_by_code_and_date(self, ts_code: str, trade_date: date) -> StockFactorRecord | None:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT * FROM stk_factor_pro WHERE ts_code = ? AND trade_date = ?"
        rows = self._conn.execute(sql, (ts_code, date_str)).fetchall()
        return self._to_model(rows[0]) if rows else None

    def find_recent(self, ts_code: str, trade_date: date, count: int = 5) -> list[StockFactorRecord]:
        """Get recent N days of factor data."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT * FROM stk_factor_pro
            WHERE ts_code = ? AND trade_date <= ?
            ORDER BY trade_date DESC LIMIT ?
        """
        rows = self._conn.execute(sql, (ts_code, date_str, count)).fetchall()
        return [self._to_model(r) for r in reversed(rows)]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> StockFactorRecord:
        return StockFactorRecord(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            close=row["close"] or 0.0,
            macd_dif=row["macd_dif"] or 0.0,
            macd_dea=row["macd_dea"] or 0.0,
            macd=row["macd"] or 0.0,
            kdj_k=row["kdj_k"] or 0.0,
            kdj_d=row["kdj_d"] or 0.0,
            kdj_j=row["kdj_j"] or 0.0,
            rsi_6=row["rsi_6"] or 0.0,
            rsi_12=row["rsi_12"] or 0.0,
            boll_upper=row["boll_upper"] or 0.0,
            boll_mid=row["boll_mid"] or 0.0,
            boll_lower=row["boll_lower"] or 0.0,
        )

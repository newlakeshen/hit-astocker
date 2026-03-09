"""Repository for 北向资金十大成交股 data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.hsgt_data import HsgtTop10Record
from hit_astocker.repositories.base import BaseRepository


class HsgtTop10Repository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "hsgt_top10")

    def find_records_by_date(self, trade_date: date) -> list[HsgtTop10Record]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_by_code(self, ts_code: str, trade_date: date) -> HsgtTop10Record | None:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_code_and_date(ts_code, date_str)
        return self._to_model(rows[0]) if rows else None

    def find_net_buyers_by_date(self, trade_date: date) -> dict[str, float]:
        """Get net buy amount for all stocks on a date. Returns {ts_code: net_amount}."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT ts_code, SUM(net_amount) as total_net
            FROM hsgt_top10 WHERE trade_date = ?
            GROUP BY ts_code
            ORDER BY total_net DESC
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return {r["ts_code"]: r["total_net"] for r in rows}

    def find_consecutive_net_buy(self, ts_code: str, trade_date: date, days: int = 5) -> int:
        """Count consecutive days of net buying up to trade_date."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT trade_date, SUM(net_amount) as daily_net
            FROM hsgt_top10
            WHERE ts_code = ? AND trade_date <= ?
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, (ts_code, date_str, days)).fetchall()
        consecutive = 0
        for r in rows:
            if r["daily_net"] > 0:
                consecutive += 1
            else:
                break
        return consecutive

    @staticmethod
    def _to_model(row: sqlite3.Row) -> HsgtTop10Record:
        return HsgtTop10Record(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            close=row["close"] or 0.0,
            change=row["change"] or 0.0,
            rank=row["rank"] or 0,
            market_type=row["market_type"] or "",
            amount=row["amount"] or 0.0,
            net_amount=row["net_amount"] or 0.0,
            buy=row["buy"] or 0.0,
            sell=row["sell"] or 0.0,
        )

"""Repository for 集合竞价 data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.auction_data import AuctionRecord
from hit_astocker.repositories.base import BaseRepository


class AuctionRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "stk_auction")

    def find_records_by_date(self, trade_date: date) -> list[AuctionRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def compute_auction_stats(self, trade_date: date) -> dict[str, float]:
        """Compute aggregate auction stats for market sentiment.

        Returns dict with:
            avg_pct: average auction gap (%)
            up_ratio: ratio of stocks gapping up (0-1)
            total_amount: total auction turnover
        """
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT
                AVG(pct_change) as avg_pct,
                SUM(CASE WHEN pct_change > 0 THEN 1.0 ELSE 0.0 END) / MAX(COUNT(*), 1) as up_ratio,
                SUM(amount) as total_amount,
                COUNT(*) as cnt
            FROM stk_auction WHERE trade_date = ?
        """
        row = self._conn.execute(sql, (date_str,)).fetchone()
        if not row or row["cnt"] == 0:
            return {}
        return {
            "avg_pct": row["avg_pct"] or 0.0,
            "up_ratio": row["up_ratio"] or 0.0,
            "total_amount": row["total_amount"] or 0.0,
            "count": row["cnt"],
        }

    @staticmethod
    def _to_model(row: sqlite3.Row) -> AuctionRecord:
        return AuctionRecord(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            open=row["open"] or 0.0,
            pre_close=row["pre_close"] or 0.0,
            change=row["change"] or 0.0,
            pct_change=row["pct_change"] or 0.0,
            vol=row["vol"] or 0.0,
            amount=row["amount"] or 0.0,
        )

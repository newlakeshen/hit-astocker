"""Repository for KPL (开盘啦) list data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.kpl_data import KplRecord
from hit_astocker.repositories.base import BaseRepository


class KplRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "kpl_list")

    def find_records_by_date(self, trade_date: date) -> list[KplRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_by_tag(self, trade_date: date, tag: str = "涨停") -> list[KplRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT * FROM kpl_list WHERE trade_date = ? AND tag = ?"
        rows = self._conn.execute(sql, (date_str, tag)).fetchall()
        return [self._to_model(r) for r in rows]

    def get_themes_by_date(self, trade_date: date) -> dict[str, int]:
        """Get theme counts for a date."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT theme, COUNT(*) as cnt
            FROM kpl_list WHERE trade_date = ? AND tag = '涨停' AND theme != ''
            GROUP BY theme ORDER BY cnt DESC
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return {r["theme"]: r["cnt"] for r in rows}

    @staticmethod
    def _to_model(row: sqlite3.Row) -> KplRecord:
        return KplRecord(
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            lu_time=row["lu_time"] or "",
            ld_time=row["ld_time"] or "",
            lu_desc=row["lu_desc"] or "",
            tag=row["tag"] or "",
            theme=row["theme"] or "",
            net_change=row["net_change"] or 0.0,
            bid_amount=row["bid_amount"] or 0.0,
            status=row["status"] or "",
            pct_chg=row["pct_chg"] or 0.0,
            amount=row["amount"] or 0.0,
            turnover_rate=row["turnover_rate"] or 0.0,
            lu_limit_order=row["lu_limit_order"] or 0.0,
        )

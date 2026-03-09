"""Repository for money flow data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.moneyflow import MoneyFlowRecord
from hit_astocker.repositories.base import BaseRepository


class MoneyFlowRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "moneyflow_ths")

    def find_records_by_date(self, trade_date: date) -> list[MoneyFlowRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_by_stock(self, trade_date: date, ts_code: str) -> MoneyFlowRecord | None:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_code_and_date(ts_code, date_str)
        return self._to_model(rows[0]) if rows else None

    def find_top_inflow(self, trade_date: date, top_n: int = 20) -> list[MoneyFlowRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT * FROM moneyflow_ths
            WHERE trade_date = ?
            ORDER BY net_amount DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, (date_str, top_n)).fetchall()
        return [self._to_model(r) for r in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> MoneyFlowRecord:
        return MoneyFlowRecord(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            pct_change=row["pct_change"] or 0.0,
            latest=row["latest"] or 0.0,
            net_amount=row["net_amount"] or 0.0,
            net_d5_amount=row["net_d5_amount"] or 0.0,
            buy_lg_amount=row["buy_lg_amount"] or 0.0,
            buy_lg_amount_rate=row["buy_lg_amount_rate"] or 0.0,
            buy_md_amount=row["buy_md_amount"] or 0.0,
            buy_md_amount_rate=row["buy_md_amount_rate"] or 0.0,
            buy_sm_amount=row["buy_sm_amount"] or 0.0,
            buy_sm_amount_rate=row["buy_sm_amount_rate"] or 0.0,
        )

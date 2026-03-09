"""Repository for detailed money flow data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.moneyflow_detail import MoneyFlowDetail
from hit_astocker.repositories.base import BaseRepository


class MoneyFlowDetailRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "moneyflow_detail")

    def find_records_by_date(self, trade_date: date) -> list[MoneyFlowDetail]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_by_stock(self, ts_code: str, trade_date: date) -> MoneyFlowDetail | None:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_code_and_date(ts_code, date_str)
        return self._to_model(rows[0]) if rows else None

    def find_by_stock_range(
        self, ts_code: str, start_date: date, end_date: date
    ) -> list[MoneyFlowDetail]:
        """Get history for a single stock across date range."""
        sql = """
            SELECT * FROM moneyflow_detail
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """
        rows = self._conn.execute(
            sql,
            (ts_code, start_date.strftime(TUSHARE_DATE_FMT), end_date.strftime(TUSHARE_DATE_FMT)),
        ).fetchall()
        return [self._to_model(r) for r in rows]

    def find_top_main_force_inflow(self, trade_date: date, top_n: int = 50) -> list[MoneyFlowDetail]:
        """Top N by main force (large + extra-large) net inflow."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT *,
                   (buy_lg_amount - sell_lg_amount + buy_elg_amount - sell_elg_amount) as main_net
            FROM moneyflow_detail
            WHERE trade_date = ?
            ORDER BY main_net DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, (date_str, top_n)).fetchall()
        return [self._to_model(r) for r in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> MoneyFlowDetail:
        return MoneyFlowDetail(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            buy_sm_vol=row["buy_sm_vol"] or 0.0,
            buy_sm_amount=row["buy_sm_amount"] or 0.0,
            sell_sm_vol=row["sell_sm_vol"] or 0.0,
            sell_sm_amount=row["sell_sm_amount"] or 0.0,
            buy_md_vol=row["buy_md_vol"] or 0.0,
            buy_md_amount=row["buy_md_amount"] or 0.0,
            sell_md_vol=row["sell_md_vol"] or 0.0,
            sell_md_amount=row["sell_md_amount"] or 0.0,
            buy_lg_vol=row["buy_lg_vol"] or 0.0,
            buy_lg_amount=row["buy_lg_amount"] or 0.0,
            sell_lg_vol=row["sell_lg_vol"] or 0.0,
            sell_lg_amount=row["sell_lg_amount"] or 0.0,
            buy_elg_vol=row["buy_elg_vol"] or 0.0,
            buy_elg_amount=row["buy_elg_amount"] or 0.0,
            sell_elg_vol=row["sell_elg_vol"] or 0.0,
            sell_elg_amount=row["sell_elg_amount"] or 0.0,
            net_mf_vol=row["net_mf_vol"] or 0.0,
            net_mf_amount=row["net_mf_amount"] or 0.0,
        )

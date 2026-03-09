"""Repository for dragon-tiger board data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.dragon_tiger import DragonTigerRecord, InstitutionalTrade
from hit_astocker.repositories.base import BaseRepository


class DragonTigerRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "top_list")

    def find_records_by_date(self, trade_date: date) -> list[DragonTigerRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> DragonTigerRecord:
        return DragonTigerRecord(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            close=row["close"] or 0.0,
            pct_change=row["pct_change"] or 0.0,
            turnover_rate=row["turnover_rate"] or 0.0,
            amount=row["amount"] or 0.0,
            l_sell=row["l_sell"] or 0.0,
            l_buy=row["l_buy"] or 0.0,
            l_amount=row["l_amount"] or 0.0,
            net_amount=row["net_amount"] or 0.0,
            net_rate=row["net_rate"] or 0.0,
            amount_rate=row["amount_rate"] or 0.0,
            float_values=row["float_values"] or 0.0,
            reason=row["reason"] or "",
        )


class InstitutionalTradeRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "top_inst")

    def find_records_by_date(self, trade_date: date) -> list[InstitutionalTrade]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_by_stock(self, trade_date: date, ts_code: str) -> list[InstitutionalTrade]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_code_and_date(ts_code, date_str)
        return [self._to_model(r) for r in rows]

    def get_institutional_net_buy(self, trade_date: date) -> dict[str, float]:
        """Get net buy amount for institutional seats by stock."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT ts_code, SUM(net_buy) as total_net
            FROM top_inst
            WHERE trade_date = ? AND exalter LIKE '%机构专用%'
            GROUP BY ts_code
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return {r["ts_code"]: r["total_net"] for r in rows}

    @staticmethod
    def _to_model(row: sqlite3.Row) -> InstitutionalTrade:
        return InstitutionalTrade(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            exalter=row["exalter"] or "",
            side=row["side"] or "",
            buy=row["buy"] or 0.0,
            buy_rate=row["buy_rate"] or 0.0,
            sell=row["sell"] or 0.0,
            sell_rate=row["sell_rate"] or 0.0,
            net_buy=row["net_buy"] or 0.0,
            reason=row["reason"] or "",
        )

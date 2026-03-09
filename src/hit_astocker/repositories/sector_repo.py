"""Repository for limit_cpt_list (sector strength) data."""

import sqlite3
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.sector import SectorStrength
from hit_astocker.repositories.base import BaseRepository


class SectorRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "limit_cpt_list")

    def find_records_by_date(self, trade_date: date) -> list[SectorStrength]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_top_sectors(self, trade_date: date, top_n: int = 10) -> list[SectorStrength]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT * FROM limit_cpt_list
            WHERE trade_date = ?
            ORDER BY up_nums DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, (date_str, top_n)).fetchall()
        return [self._to_model(r) for r in rows]

    def find_sector_names_by_date(self, trade_date: date, top_n: int = 10) -> set[str]:
        sectors = self.find_top_sectors(trade_date, top_n)
        return {s.name for s in sectors}

    @staticmethod
    def _to_model(row: sqlite3.Row) -> SectorStrength:
        return SectorStrength(
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            days=row["days"] or 0,
            up_stat=row["up_stat"] or "",
            cons_nums=row["cons_nums"] or 0,
            up_nums=row["up_nums"] or 0,
            pct_chg=row["pct_chg"] or 0.0,
            rank=row["rank"] or "",
        )

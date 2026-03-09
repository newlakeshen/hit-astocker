"""Sector rotation tracking engine.

Tracks daily sector rankings, detects rotation events,
and identifies sector leaders.
"""

import sqlite3
from datetime import date

from hit_astocker.models.sector import SectorRotationResult, SectorStrength
from hit_astocker.repositories.kpl_repo import KplRepository
from hit_astocker.repositories.sector_repo import SectorRepository
from hit_astocker.utils.date_utils import get_previous_trading_day


class SectorRotationAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._sector_repo = SectorRepository(conn)
        self._kpl_repo = KplRepository(conn)

    def analyze(self, trade_date: date, top_n: int = 10) -> SectorRotationResult:
        today_sectors = self._sector_repo.find_top_sectors(trade_date, top_n)

        prev_date = get_previous_trading_day(trade_date)
        yesterday_names = (
            self._sector_repo.find_sector_names_by_date(prev_date, top_n)
            if prev_date
            else set()
        )

        today_names = {s.name for s in today_sectors}

        continuing = today_names & yesterday_names
        new_sectors = today_names - yesterday_names
        dropped = yesterday_names - today_names
        rotation_detected = len(new_sectors) >= 3 or len(dropped) >= 3

        # Map sector leaders using KPL theme data
        sector_leaders = self._map_sector_leaders(trade_date, today_sectors)

        return SectorRotationResult(
            trade_date=trade_date,
            top_sectors=tuple(today_sectors),
            continuing_sectors=tuple(sorted(continuing)),
            new_sectors=tuple(sorted(new_sectors)),
            dropped_sectors=tuple(sorted(dropped)),
            rotation_detected=rotation_detected,
            sector_leaders=sector_leaders,
        )

    def _map_sector_leaders(
        self, trade_date: date, sectors: list[SectorStrength]
    ) -> dict[str, tuple[str, ...]]:
        """Map each sector to its limit-up leaders via KPL theme data."""
        kpl_records = self._kpl_repo.find_by_tag(trade_date, tag="涨停")
        theme_to_codes: dict[str, list[str]] = {}
        for rec in kpl_records:
            if rec.theme:
                for theme in rec.theme.split("+"):
                    theme = theme.strip()
                    if theme not in theme_to_codes:
                        theme_to_codes[theme] = []
                    theme_to_codes[theme].append(rec.ts_code)

        result = {}
        for sector in sectors:
            codes = theme_to_codes.get(sector.name, [])
            result[sector.name] = tuple(codes[:5])  # Top 5 leaders per sector
        return result

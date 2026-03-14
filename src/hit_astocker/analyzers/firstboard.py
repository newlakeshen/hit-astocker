"""First-board (首板) analysis engine.

Evaluates first-time limit-up stocks on:
- Seal timing (封板时间)
- Seal strength (封板强度: 封单金额/流通市值)
- Board purity (开板次数)
- Turnover analysis
- Sector alignment
"""

import sqlite3
from datetime import date

from hit_astocker.config.constants import (
    PURITY_DEFAULT_SCORE,
    PURITY_SCORES,
    SEAL_TIME_AVERAGE,
    SEAL_TIME_EXCELLENT,
    SEAL_TIME_GOOD,
)
from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.analysis_result import FirstBoardResult
from hit_astocker.models.limit_data import LimitRecord
from hit_astocker.repositories.kpl_repo import KplRepository, split_themes
from hit_astocker.repositories.limit_repo import LimitListRepository
from hit_astocker.repositories.sector_repo import SectorRepository


class FirstBoardAnalyzer:
    def __init__(
        self, conn: sqlite3.Connection, settings: Settings | None = None,
        *, limit_repo=None, kpl_repo=None,
    ):
        self._limit_repo = limit_repo or LimitListRepository(conn)
        self._kpl_repo = kpl_repo or KplRepository(conn)
        self._sector_repo = SectorRepository(conn)
        self._settings = settings or get_settings()

    def analyze(self, trade_date: date) -> list[FirstBoardResult]:
        first_boards = self._limit_repo.find_first_board_stocks(trade_date)
        if not first_boards:
            return []

        top_sectors = self._sector_repo.find_sector_names_by_date(trade_date, top_n=5)
        kpl_map = {
            rec.ts_code: rec
            for rec in self._kpl_repo.find_by_tag(trade_date, tag="涨停")
        }

        results = []
        for record in first_boards:
            result = self._score_stock(record, top_sectors, kpl_map.get(record.ts_code))
            results.append(result)

        return sorted(results, key=lambda r: r.composite_score, reverse=True)

    def _score_stock(
        self,
        record: LimitRecord,
        top_sectors: set[str],
        kpl_record=None,
    ) -> FirstBoardResult:
        s = self._settings

        seal_time_score = self._score_seal_time(record.first_time)
        seal_amount = self._resolve_seal_amount(record, kpl_record)
        seal_strength_score = self._score_seal_strength(seal_amount, record.float_mv)
        purity_score = self._score_purity(record.open_times)
        turnover_score = self._score_turnover(record.turnover_ratio, record.open_times)
        sector_score, sector_name = self._score_sector(record.industry, top_sectors, kpl_record)

        composite = (
            s.first_board_seal_time_weight * seal_time_score
            + s.first_board_seal_strength_weight * seal_strength_score
            + s.first_board_purity_weight * purity_score
            + s.first_board_turnover_weight * turnover_score
            + s.first_board_sector_weight * sector_score
        )

        return FirstBoardResult(
            trade_date=record.trade_date,
            ts_code=record.ts_code,
            name=record.name,
            industry=record.industry,
            close=record.close,
            pct_chg=record.pct_chg,
            seal_time_score=round(seal_time_score, 2),
            seal_strength_score=round(seal_strength_score, 2),
            purity_score=round(purity_score, 2),
            turnover_score=round(turnover_score, 2),
            sector_score=round(sector_score, 2),
            composite_score=round(composite, 2),
            first_time=record.first_time,
            open_times=record.open_times,
            limit_amount=seal_amount,
            float_mv=record.float_mv,
            turnover_ratio=record.turnover_ratio,
            sector_name=sector_name,
        )

    @staticmethod
    def _resolve_seal_amount(record: LimitRecord, kpl_record) -> float:
        """Prefer KPL封单金额, falling back to limit_list_d.limit_amount."""
        if kpl_record and kpl_record.lu_limit_order > 0:
            return kpl_record.lu_limit_order
        return record.limit_amount

    @staticmethod
    def _score_seal_time(first_time: str) -> float:
        if not first_time:
            return 25.0
        t = first_time.replace(":", "")[:4]  # "09:30:00" -> "0930"
        if t < SEAL_TIME_EXCELLENT.replace(":", ""):
            return 100.0
        if t < SEAL_TIME_GOOD.replace(":", ""):
            return 75.0
        if t < SEAL_TIME_AVERAGE.replace(":", ""):
            return 50.0
        return 25.0

    @staticmethod
    def _score_seal_strength(limit_amount: float, float_mv: float) -> float:
        """Score based on seal amount relative to float market value."""
        if float_mv <= 0:
            return 50.0
        ratio = limit_amount / float_mv
        # ratio > 0.1 (10%) is very strong, 0.05 is good, < 0.01 is weak
        if ratio >= 0.10:
            return 100.0
        if ratio >= 0.05:
            return 75.0
        if ratio >= 0.02:
            return 50.0
        return 25.0

    @staticmethod
    def _score_purity(open_times: int) -> float:
        return float(PURITY_SCORES.get(open_times, PURITY_DEFAULT_SCORE))

    @staticmethod
    def _score_turnover(turnover_ratio: float, open_times: int) -> float:
        """Low turnover with good seal = strong; high turnover with opens = weak."""
        if open_times == 0:
            # One-shot seal: lower turnover is better
            if turnover_ratio < 5:
                return 100.0
            if turnover_ratio < 10:
                return 75.0
            if turnover_ratio < 20:
                return 50.0
            return 30.0
        else:
            # With opens: moderate turnover acceptable
            if turnover_ratio < 10:
                return 70.0
            if turnover_ratio < 20:
                return 50.0
            return 25.0

    @staticmethod
    def _score_sector(industry: str, top_sectors: set[str], kpl_record) -> tuple[float, str]:
        """Score based on KPL themes first, then fall back to industry names."""
        if kpl_record and kpl_record.theme:
            for theme in split_themes(kpl_record.theme):
                if theme in top_sectors:
                    return 100.0, theme
            primary_theme = split_themes(kpl_record.theme)
            if primary_theme:
                return 45.0, primary_theme[0]

        if industry and industry in top_sectors:
            return 100.0, industry
        if industry:
            return 30.0, industry
        return 30.0, ""

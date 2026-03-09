"""Consecutive board (连板) analysis engine.

Builds the "连板天梯" (board ladder) and computes:
- Per-tier stock lists and promotion rates
- Market leader (空间板) identification
- Height trends over trailing days
"""

import sqlite3
from datetime import date

from hit_astocker.models.analysis_result import LianbanResult, LianbanTier
from hit_astocker.repositories.limit_step_repo import LimitStepRepository
from hit_astocker.utils.date_utils import get_previous_trading_day, get_recent_trading_days


class LianbanAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._step_repo = LimitStepRepository(conn)

    def analyze(self, trade_date: date, trend_days: int = 10) -> LianbanResult:
        records = self._step_repo.find_records_by_date(trade_date)
        today_counts = self._step_repo.get_height_counts(trade_date)

        # Previous day counts for promotion rate calculation
        prev_date = get_previous_trading_day(trade_date)
        yesterday_counts = (
            self._step_repo.get_height_counts(prev_date) if prev_date else {}
        )

        # Build tiers
        heights_by_level: dict[int, tuple[list[str], list[str]]] = {}  # height -> (codes, names)
        for rec in records:
            h = rec.nums
            if h not in heights_by_level:
                heights_by_level[h] = ([], [])
            heights_by_level[h][0].append(rec.ts_code)
            heights_by_level[h][1].append(rec.name)

        tiers = []
        for height in sorted(heights_by_level.keys(), reverse=True):
            codes, names = heights_by_level[height]
            count = len(codes)
            yest_count = yesterday_counts.get(height - 1, 0) if height > 1 else 0
            promo_rate = count / max(yest_count, 1) if yest_count > 0 else 0.0

            tiers.append(LianbanTier(
                height=height,
                stocks=tuple(codes),
                stock_names=tuple(names),
                count=count,
                yesterday_count=yest_count,
                promotion_rate=round(promo_rate, 4),
            ))

        # Identify leader
        max_height = max(heights_by_level.keys()) if heights_by_level else 0
        leader_code = ""
        leader_name = ""
        if max_height > 0 and max_height in heights_by_level:
            leader_code = heights_by_level[max_height][0][0]
            leader_name = heights_by_level[max_height][1][0]

        # Total lianban count (>= 2 boards)
        total_lianban = sum(len(codes) for h, (codes, _) in heights_by_level.items() if h >= 2)

        # Average promotion rate across tiers
        promo_rates = [t.promotion_rate for t in tiers if t.height >= 2]
        avg_promo = sum(promo_rates) / max(len(promo_rates), 1) if promo_rates else 0.0

        # Height trend
        height_trend = self._compute_height_trend(trade_date, trend_days)

        return LianbanResult(
            trade_date=trade_date,
            tiers=tuple(tiers),
            max_height=max_height,
            leader_code=leader_code,
            leader_name=leader_name,
            total_lianban_count=total_lianban,
            avg_promotion_rate=round(avg_promo, 4),
            height_trend=height_trend,
        )

    def _compute_height_trend(self, trade_date: date, days: int) -> tuple[int, ...]:
        """Get max consecutive board height for each of the trailing N days."""
        recent = get_recent_trading_days(trade_date, days)
        heights = []
        for d in recent:
            h = self._step_repo.get_max_height(d)
            heights.append(h)
        heights.reverse()  # oldest first
        # Append today
        heights.append(self._step_repo.get_max_height(trade_date))
        return tuple(heights)

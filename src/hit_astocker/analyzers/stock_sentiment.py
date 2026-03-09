"""Per-stock sentiment scoring engine.

Combines multiple dimensions to assess individual stock "热度" (heat/popularity):
- Volume ratio (量比): today's volume vs recent average
- Seal order strength (封单强度): from KPL lu_limit_order
- Bid activity (竞价活跃度): from KPL bid_amount
- Theme heat (题材热度): from event classifier
- Event catalyst (事件催化): from lu_desc classification
"""

import sqlite3
from datetime import date

from hit_astocker.analyzers.event_classifier import EventClassifier
from hit_astocker.models.event_data import StockSentimentScore
from hit_astocker.repositories.daily_bar_repo import DailyBarRepository
from hit_astocker.repositories.kpl_repo import KplRepository


class StockSentimentAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._bar_repo = DailyBarRepository(conn)
        self._kpl_repo = KplRepository(conn)
        self._event_classifier = EventClassifier(conn)

    def analyze(self, trade_date: date, ts_codes: list[str] | None = None) -> list[StockSentimentScore]:
        """Compute per-stock sentiment scores."""
        # Load KPL data for all limit-up stocks
        kpl_records = self._kpl_repo.find_by_tag(trade_date, tag="涨停")
        kpl_map = {rec.ts_code: rec for rec in kpl_records}

        # Event analysis for theme heat
        event_result = self._event_classifier.analyze(trade_date)
        theme_heat_map = {th.theme_name: th.heat_score for th in event_result.theme_heats}
        event_map = {ev.ts_code: ev for ev in event_result.stock_events}

        # Determine which codes to analyze
        codes = ts_codes if ts_codes else list(kpl_map.keys())

        results = []
        for ts_code in codes:
            kpl = kpl_map.get(ts_code)
            event = event_map.get(ts_code)

            # Volume ratio
            volume_ratio_score = self._score_volume_ratio(ts_code, trade_date)

            # Seal order score
            seal_score = self._score_seal_order(kpl)

            # Bid activity
            bid_score = self._score_bid_activity(kpl)

            # Theme heat score
            theme_score = self._score_theme_heat(kpl, theme_heat_map)

            # Event catalyst score
            event_score = self._score_event_catalyst(event)

            # Composite: weighted sum
            composite = (
                0.25 * volume_ratio_score
                + 0.20 * seal_score
                + 0.15 * bid_score
                + 0.20 * theme_score
                + 0.20 * event_score
            )

            name = kpl.name if kpl else ts_code
            results.append(StockSentimentScore(
                ts_code=ts_code,
                name=name,
                volume_ratio_score=round(volume_ratio_score, 2),
                seal_order_score=round(seal_score, 2),
                bid_activity_score=round(bid_score, 2),
                theme_heat_score=round(theme_score, 2),
                event_catalyst_score=round(event_score, 2),
                composite_score=round(composite, 2),
                factors={
                    "volume_ratio": round(volume_ratio_score, 2),
                    "seal_order": round(seal_score, 2),
                    "bid_activity": round(bid_score, 2),
                    "theme_heat": round(theme_score, 2),
                    "event_catalyst": round(event_score, 2),
                },
            ))

        return sorted(results, key=lambda s: s.composite_score, reverse=True)

    def _score_volume_ratio(self, ts_code: str, trade_date: date) -> float:
        """Score based on today's volume relative to 5-day average.

        量比 > 3 = 极度活跃, 2-3 = 活跃, 1-2 = 正常, < 1 = 冷淡
        """
        bars = self._bar_repo.find_recent_bars(ts_code, trade_date, count=6)
        if len(bars) < 2:
            return 50.0

        today_bar = bars[-1]
        if today_bar.trade_date != trade_date:
            return 50.0

        # 5-day average volume (excluding today)
        prev_bars = bars[:-1]
        if not prev_bars:
            return 50.0

        avg_vol = sum(b.vol for b in prev_bars) / len(prev_bars)
        if avg_vol <= 0:
            return 50.0

        volume_ratio = today_bar.vol / avg_vol

        if volume_ratio >= 4.0:
            return 100.0
        if volume_ratio >= 3.0:
            return 90.0
        if volume_ratio >= 2.0:
            return 75.0
        if volume_ratio >= 1.5:
            return 60.0
        if volume_ratio >= 1.0:
            return 45.0
        return 25.0

    @staticmethod
    def _score_seal_order(kpl) -> float:
        """Score based on lu_limit_order (封单金额).

        封单 > 5亿 = 顶级, 2-5亿 = 强, 1-2亿 = 中, 0.5-1亿 = 弱, < 0.5亿 = 极弱
        """
        if not kpl or kpl.lu_limit_order <= 0:
            return 30.0

        order = kpl.lu_limit_order  # 单位: 万元
        if order >= 50000:  # 5亿
            return 100.0
        if order >= 20000:  # 2亿
            return 85.0
        if order >= 10000:  # 1亿
            return 70.0
        if order >= 5000:  # 5000万
            return 55.0
        return 35.0

    @staticmethod
    def _score_bid_activity(kpl) -> float:
        """Score based on bid_amount (竞价成交额).

        竞价额越高 = 市场对该股关注度越高
        """
        if not kpl or kpl.bid_amount <= 0:
            return 30.0

        bid = kpl.bid_amount  # 单位: 万元
        if bid >= 10000:  # 1亿
            return 100.0
        if bid >= 5000:  # 5000万
            return 80.0
        if bid >= 2000:  # 2000万
            return 60.0
        if bid >= 1000:  # 1000万
            return 45.0
        return 30.0

    @staticmethod
    def _score_theme_heat(kpl, theme_heat_map: dict[str, float]) -> float:
        """Score based on the stock's theme heat.

        Take the highest heat score among all themes the stock belongs to.
        """
        if not kpl or not kpl.theme:
            return 30.0

        themes = [t.strip() for t in kpl.theme.split("+") if t.strip()]
        if not themes:
            return 30.0

        max_heat = max(theme_heat_map.get(t, 30.0) for t in themes)
        return max_heat

    @staticmethod
    def _score_event_catalyst(event) -> float:
        """Score based on event classification weight.

        强催化 (政策/重组) = 高分, 弱催化 (技术/未知) = 低分
        """
        if not event:
            return 40.0

        # event_weight is 0-1, scale to 0-100
        return event.event_weight * 100

"""Per-stock sentiment scoring engine (dynamic-weight).

Combines up to 8 dimensions to assess individual stock "热度" (heat/popularity).
Factors whose backing tables are empty are **excluded** from weighting and their
weight is redistributed proportionally to factors with real data.

Core 5 (always available — backed by kpl_list + daily_bar):
- Volume ratio (量比): today's volume vs recent average
- Seal order strength (封单强度): from KPL lu_limit_order
- Bid activity (竞价活跃度): from KPL bid_amount
- Theme heat (题材热度): from event classifier
- Event catalyst (事件催化): from lu_desc classification

Optional 3 (require synced tables):
- Popularity ranking (同花顺人气): from ths_hot
- Northbound signal (北向资金): from hsgt_top10
- Technical form (技术形态): from stk_factor_pro
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import TYPE_CHECKING

from hit_astocker.analyzers.event_classifier import EventClassifier
from hit_astocker.analyzers.technical_form import TechnicalFormAnalyzer
from hit_astocker.models.event_data import StockSentimentScore
from hit_astocker.repositories.daily_bar_repo import DailyBarRepository
from hit_astocker.repositories.hsgt_repo import HsgtTop10Repository
from hit_astocker.repositories.kpl_repo import KplRepository, split_themes
from hit_astocker.repositories.ths_hot_repo import ThsHotRepository

if TYPE_CHECKING:
    from hit_astocker.models.daily_context import DataCoverage
    from hit_astocker.models.event_data import EventAnalysisResult


# ── Base weights (sum=1.0 when all 8 active) ──────────────────────────
_BASE_WEIGHTS: dict[str, float] = {
    "volume_ratio": 0.15,
    "seal_order": 0.14,
    "bid_activity": 0.08,
    "theme_heat": 0.12,
    "event_catalyst": 0.11,
    "popularity": 0.15,
    "northbound": 0.13,
    "technical_form": 0.12,
}


def _renormalized_weights(active_keys: set[str]) -> dict[str, float]:
    """Return weights renormalized to sum=1 for active factor keys only."""
    raw = {k: v for k, v in _BASE_WEIGHTS.items() if k in active_keys}
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in raw.items()}


class StockSentimentAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._bar_repo = DailyBarRepository(conn)
        self._kpl_repo = KplRepository(conn)
        self._event_classifier = EventClassifier(conn)
        self._ths_hot_repo = ThsHotRepository(conn)
        self._hsgt_repo = HsgtTop10Repository(conn)
        self._technical_analyzer = TechnicalFormAnalyzer(conn)

    def analyze(
        self,
        trade_date: date,
        ts_codes: list[str] | None = None,
        coverage: DataCoverage | None = None,
        event_result: EventAnalysisResult | None = None,
    ) -> list[StockSentimentScore]:
        """Compute per-stock sentiment scores with dynamic factor weighting."""
        # Load KPL data for all limit-up stocks
        kpl_records = self._kpl_repo.find_by_tag(trade_date, tag="涨停")
        kpl_map = {rec.ts_code: rec for rec in kpl_records}

        # Event analysis for theme heat
        if event_result is None:
            event_result = self._event_classifier.analyze(trade_date)
        theme_heat_map = {th.theme_name: th.heat_score for th in event_result.theme_heats}
        event_map = {ev.ts_code: ev for ev in event_result.stock_events}

        # Determine which codes to analyze
        codes = ts_codes if ts_codes else list(kpl_map.keys())

        # Batch load: THS hot rankings
        ths_hot_map = {
            rec.ts_code: rec
            for rec in self._ths_hot_repo.find_records_by_date(trade_date)
        }

        # Batch load: Northbound capital net buyers
        hsgt_net_map = self._hsgt_repo.find_net_buyers_by_date(trade_date)

        # Batch load: Technical form scores (already uses batch internally)
        tech_scores = self._technical_analyzer.analyze(trade_date, codes)
        tech_map = {ts.ts_code: ts for ts in tech_scores}

        # Batch load: Recent daily bars for volume ratio (replaces N+1)
        bars_map = self._bar_repo.find_recent_bars_batch(codes, trade_date, count=6)

        # ── Determine active factors ──
        # Use explicit coverage when available; otherwise detect from batch data
        has_ths_hot = coverage.has_ths_hot if coverage else len(ths_hot_map) > 0
        has_hsgt = coverage.has_hsgt if coverage else len(hsgt_net_map) > 0
        has_tech = coverage.has_stk_factor if coverage else len(tech_map) > 0

        active_keys = {"volume_ratio", "seal_order", "bid_activity", "theme_heat", "event_catalyst"}
        if has_ths_hot:
            active_keys.add("popularity")
        if has_hsgt:
            active_keys.add("northbound")
        if has_tech:
            active_keys.add("technical_form")

        weights = _renormalized_weights(active_keys)

        results = []
        for ts_code in codes:
            kpl = kpl_map.get(ts_code)
            event = event_map.get(ts_code)

            # Core factor scores (always computed)
            scores: dict[str, float] = {
                "volume_ratio": self._score_volume_ratio_from_bars(
                    bars_map.get(ts_code, []), trade_date,
                ),
                "seal_order": self._score_seal_order(kpl),
                "bid_activity": self._score_bid_activity(kpl),
                "theme_heat": self._score_theme_heat(kpl, theme_heat_map),
                "event_catalyst": self._score_event_catalyst(event),
            }

            # Optional factor scores (only when backing data exists)
            popularity_score = self._score_popularity(ts_code, ths_hot_map) if has_ths_hot else 0.0
            northbound_score = self._score_northbound(ts_code, hsgt_net_map) if has_hsgt else 0.0
            tech_form = tech_map.get(ts_code)
            technical_score = (
                tech_form.composite_score if tech_form else 50.0
            ) if has_tech else 0.0

            if has_ths_hot:
                scores["popularity"] = popularity_score
            if has_hsgt:
                scores["northbound"] = northbound_score
            if has_tech:
                scores["technical_form"] = technical_score

            # Dynamic weighted composite (only active factors contribute)
            composite = sum(weights.get(k, 0) * v for k, v in scores.items())

            name = kpl.name if kpl else ts_code
            results.append(StockSentimentScore(
                ts_code=ts_code,
                name=name,
                volume_ratio_score=round(scores["volume_ratio"], 2),
                seal_order_score=round(scores["seal_order"], 2),
                bid_activity_score=round(scores["bid_activity"], 2),
                theme_heat_score=round(scores["theme_heat"], 2),
                event_catalyst_score=round(scores["event_catalyst"], 2),
                popularity_score=round(popularity_score, 2),
                northbound_score=round(northbound_score, 2),
                technical_form_score=round(technical_score, 2),
                composite_score=round(composite, 2),
                factors={k: round(v, 2) for k, v in scores.items()},
            ))

        return sorted(results, key=lambda s: s.composite_score, reverse=True)

    @staticmethod
    def _score_volume_ratio_from_bars(bars: list, trade_date: date) -> float:
        """Score volume ratio from pre-loaded bar data."""
        if len(bars) < 2:
            return 50.0

        today_bar = bars[-1]
        if today_bar.trade_date != trade_date:
            return 50.0

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
        """Score based on lu_limit_order (封单金额)."""
        if not kpl or kpl.lu_limit_order <= 0:
            return 30.0

        order = kpl.lu_limit_order
        if order >= 50000:
            return 100.0
        if order >= 20000:
            return 85.0
        if order >= 10000:
            return 70.0
        if order >= 5000:
            return 55.0
        return 35.0

    @staticmethod
    def _score_bid_activity(kpl) -> float:
        """Score based on bid_amount (竞价成交额)."""
        if not kpl or kpl.bid_amount <= 0:
            return 30.0

        bid = kpl.bid_amount
        if bid >= 10000:
            return 100.0
        if bid >= 5000:
            return 80.0
        if bid >= 2000:
            return 60.0
        if bid >= 1000:
            return 45.0
        return 30.0

    @staticmethod
    def _score_theme_heat(kpl, theme_heat_map: dict[str, float]) -> float:
        """Score based on the stock's theme heat."""
        if not kpl or not kpl.theme:
            return 30.0

        themes = split_themes(kpl.theme)
        if not themes:
            return 30.0

        max_heat = max(theme_heat_map.get(t, 30.0) for t in themes)
        return max_heat

    @staticmethod
    def _score_event_catalyst(event) -> float:
        """Score based on event classification weight."""
        if not event:
            return 40.0
        return event.event_weight * 100

    @staticmethod
    def _score_popularity(ts_code: str, ths_hot_map: dict) -> float:
        """Score based on 同花顺热股排名.

        排名越高 = 市场关注度越高 = 打板跟风盘越多.
        Top 10 = 100, Top 20 = 85, Top 50 = 70, Top 100 = 55, 未上榜 = 30
        """
        rec = ths_hot_map.get(ts_code)
        if not rec:
            return 30.0

        rank = rec.rank
        if rank <= 10:
            return 100.0
        if rank <= 20:
            return 85.0
        if rank <= 50:
            return 70.0
        if rank <= 100:
            return 55.0
        return 40.0

    @staticmethod
    def _score_northbound(ts_code: str, hsgt_net_map: dict[str, float]) -> float:
        """Score based on 北向资金净买入.

        北向在十大成交股中 + 净买入 = 聪明钱认可信号.
        净买入>1亿 = 100, >5000万 = 85, >0 = 70, 净卖出 = 30, 未出现 = 45
        """
        net = hsgt_net_map.get(ts_code)
        if net is None:
            return 45.0  # Not in top 10 = neutral

        if net >= 10000:  # > 1亿 (万元)
            return 100.0
        if net >= 5000:  # > 5000万
            return 85.0
        if net > 0:
            return 70.0
        if net > -5000:
            return 35.0
        return 20.0  # Heavy selling

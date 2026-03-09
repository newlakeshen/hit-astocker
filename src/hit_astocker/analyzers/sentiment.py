"""Market sentiment scoring engine.

Computes a composite sentiment score based on:
- Limit-up vs limit-down ratio (涨停/跌停比)
- Broken board rate (炸板率)
- Consecutive board height and promotion rate (连板高度/晋级率)
- Money effect scoring (赚钱效应)
"""

import sqlite3
from datetime import date

from hit_astocker.analyzers.market_context import MarketContextAnalyzer
from hit_astocker.config.constants import MAX_HEIGHT_NORM, SENTIMENT_LABELS
from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.index_data import MarketContext
from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.repositories.limit_repo import LimitListRepository
from hit_astocker.repositories.limit_step_repo import LimitStepRepository
from hit_astocker.utils.date_utils import get_previous_trading_day


class SentimentAnalyzer:
    def __init__(self, conn: sqlite3.Connection, settings: Settings | None = None):
        self._limit_repo = LimitListRepository(conn)
        self._step_repo = LimitStepRepository(conn)
        self._market_ctx_analyzer = MarketContextAnalyzer(conn)
        self._settings = settings or get_settings()

    def analyze(self, trade_date: date) -> SentimentScore:
        # 1. Count limit-up, limit-down, broken
        counts = self._limit_repo.count_by_type(trade_date)
        up_count = counts.get("U", 0)
        down_count = counts.get("D", 0)
        broken_count = counts.get("Z", 0)

        # 2. Ratios
        up_down_ratio = up_count / max(down_count, 1)
        broken_rate = broken_count / max(up_count + broken_count, 1)

        # 3. Consecutive board analysis
        max_height = self._step_repo.get_max_height(trade_date)
        height_counts = self._step_repo.get_height_counts(trade_date)
        total_lianban = sum(height_counts.values())
        avg_height = (
            sum(h * c for h, c in height_counts.items()) / max(total_lianban, 1)
        )

        # 4. Promotion rate (today's N+1 board count / yesterday's N board count)
        promotion_rate = self._compute_promotion_rate(trade_date)

        # 5. Score components
        s = self._settings
        ratio_score = min(up_down_ratio / 5.0 * 100, 100)  # 5:1 ratio = 100
        broken_score = (1 - broken_rate) * 100
        promo_score = promotion_rate * 100
        height_score = min(max_height / MAX_HEIGHT_NORM * 100, 100)

        # First board trend (simplified: use up_count as proxy)
        fb_trend_score = min(up_count / 60.0 * 100, 100)  # 60+ limit-ups = 100

        # 6. Weighted composite
        money_effect = (
            s.sentiment_up_down_ratio_weight * ratio_score
            + s.sentiment_broken_rate_weight * broken_score
            + s.sentiment_promotion_rate_weight * promo_score
            + s.sentiment_max_height_weight * height_score
            + s.sentiment_first_board_trend_weight * fb_trend_score
        )

        # 6b. Market context adjustment (大盘联动)
        market_ctx = self._market_ctx_analyzer.analyze(trade_date)
        money_effect = self._apply_market_adjustment(money_effect, market_ctx)

        overall = max(0, min(100, money_effect))

        # 7. Risk level
        risk_level = self._determine_risk(overall, broken_rate)

        # 8. Description
        description = self._describe_market(overall)

        return SentimentScore(
            trade_date=trade_date,
            limit_up_count=up_count,
            limit_down_count=down_count,
            broken_count=broken_count,
            up_down_ratio=round(up_down_ratio, 2),
            broken_rate=round(broken_rate, 4),
            max_consecutive_height=max_height,
            avg_consecutive_height=round(avg_height, 2),
            promotion_rate=round(promotion_rate, 4),
            money_effect_score=round(money_effect, 2),
            overall_score=round(overall, 2),
            risk_level=risk_level,
            description=description,
            market_context=market_ctx,
        )

    def _compute_promotion_rate(self, trade_date: date) -> float:
        """Compute promotion rate: stocks advancing from N to N+1 board."""
        prev_date = get_previous_trading_day(trade_date)
        if prev_date is None:
            return 0.0

        today_counts = self._step_repo.get_height_counts(trade_date)
        yesterday_counts = self._step_repo.get_height_counts(prev_date)

        if not yesterday_counts:
            return 0.0

        promoted = 0
        total_candidates = 0
        for height, count in yesterday_counts.items():
            total_candidates += count
            promoted += today_counts.get(height + 1, 0)

        return promoted / max(total_candidates, 1)

    def _determine_risk(self, score: float, broken_rate: float) -> str:
        s = self._settings
        if score < s.risk_extreme_score or broken_rate > s.risk_extreme_broken_rate:
            return "EXTREME"
        if score < s.risk_high_score or broken_rate > s.risk_high_broken_rate:
            return "HIGH"
        if score < s.risk_medium_score:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _apply_market_adjustment(score: float, ctx: MarketContext | None) -> float:
        """Adjust sentiment score based on market index context.

        - 大盘大跌 (index < -2%): penalty up to -15 points
        - 大盘大涨 (index > +1.5%): bonus up to +10 points
        - MA position: above MA20 → bonus, below MA20 → penalty
        """
        if ctx is None:
            return score

        adjustment = 0.0

        # Intraday index return impact
        avg_pct = (ctx.sh_pct_chg + ctx.gem_pct_chg) / 2
        if avg_pct <= -2.0:
            adjustment -= 15.0
        elif avg_pct <= -1.0:
            adjustment -= 8.0
        elif avg_pct >= 2.0:
            adjustment += 10.0
        elif avg_pct >= 1.0:
            adjustment += 5.0

        # MA20 trend position: above MA20 = bullish environment
        if ctx.sh_ma20_ratio >= 1.02:
            adjustment += 5.0
        elif ctx.sh_ma20_ratio <= 0.97:
            adjustment -= 8.0

        return score + adjustment

    @staticmethod
    def _describe_market(score: float) -> str:
        for (low, high), label in SENTIMENT_LABELS.items():
            if low <= score < high:
                return label
        return "未知 (Unknown)"

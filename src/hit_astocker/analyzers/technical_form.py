"""技术形态分析器.

Uses stk_factor_pro data (MACD/KDJ/RSI/BOLL) to assess
whether a stock is in a technically favorable position for 打板.

Key signals for limit-up candidates:
- MACD金叉 (golden cross): DIF crosses above DEA
- KDJ超卖反弹: J < 20 then reversal
- RSI位置: Not overbought (RSI6 < 80)
- BOLL位置: Price near upper band = strong trend
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from hit_astocker.repositories.stk_factor_repo import StockFactorRepository


@dataclass(frozen=True)
class TechnicalFormScore:
    """个股技术形态评分."""

    ts_code: str
    macd_score: float  # MACD信号评分 (0-100)
    kdj_score: float  # KDJ位置评分 (0-100)
    rsi_score: float  # RSI超买超卖评分 (0-100)
    boll_score: float  # BOLL带位置评分 (0-100)
    composite_score: float  # 综合技术形态 (0-100)


class TechnicalFormAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._factor_repo = StockFactorRepository(conn)

    def analyze(self, trade_date: date, ts_codes: list[str]) -> list[TechnicalFormScore]:
        """Compute technical form scores for candidate stocks (batch query)."""
        if not ts_codes:
            return []

        # Batch load recent 3 days of factors for ALL codes in one query
        factors_map = self._factor_repo.find_recent_batch(ts_codes, trade_date, count=3)

        results = []
        for code in ts_codes:
            factors = factors_map.get(code, [])
            score = self._score_from_factors(code, factors)
            results.append(score)
        return results

    @classmethod
    def _score_from_factors(cls, ts_code: str, factors: list) -> TechnicalFormScore:
        """Score a stock from pre-loaded factor data."""
        if not factors:
            return TechnicalFormScore(
                ts_code=ts_code,
                macd_score=50.0, kdj_score=50.0,
                rsi_score=50.0, boll_score=50.0,
                composite_score=50.0,
            )

        latest = factors[-1]
        prev = factors[-2] if len(factors) >= 2 else None

        macd_score = cls._score_macd(latest, prev)
        kdj_score = cls._score_kdj(latest)
        rsi_score = cls._score_rsi(latest)
        boll_score = cls._score_boll(latest)

        # Weights: MACD(35%) + KDJ(20%) + RSI(25%) + BOLL(20%)
        composite = (
            0.35 * macd_score
            + 0.20 * kdj_score
            + 0.25 * rsi_score
            + 0.20 * boll_score
        )

        return TechnicalFormScore(
            ts_code=ts_code,
            macd_score=round(macd_score, 2),
            kdj_score=round(kdj_score, 2),
            rsi_score=round(rsi_score, 2),
            boll_score=round(boll_score, 2),
            composite_score=round(composite, 2),
        )

    @staticmethod
    def _score_macd(latest, prev) -> float:
        """Score MACD signal.

        打板视角:
        - MACD金叉(DIF上穿DEA): 最佳, 90-100
        - MACD红柱放大: 趋势加速, 70-90
        - MACD红柱缩小: 趋势减弱, 40-60
        - MACD死叉: 不利, 10-30
        - 零轴以上金叉 > 零轴以下金叉
        """
        if latest.macd_dif == 0 and latest.macd_dea == 0:
            return 50.0

        # Golden cross detection
        if prev:
            was_below = prev.macd_dif <= prev.macd_dea
            is_above = latest.macd_dif > latest.macd_dea
            if was_below and is_above:
                # Golden cross: bonus if above zero axis
                return 95.0 if latest.macd_dif > 0 else 85.0

            was_above = prev.macd_dif > prev.macd_dea
            is_below = latest.macd_dif <= latest.macd_dea
            if was_above and is_below:
                return 20.0  # Death cross

        # MACD bar direction
        if latest.macd > 0:
            # Red bar
            if prev and latest.macd > prev.macd:
                return 80.0  # Expanding red
            return 65.0  # Red but not expanding
        else:
            # Green bar
            if prev and latest.macd > prev.macd:
                return 45.0  # Shrinking green (improving)
            return 25.0  # Expanding green (deteriorating)

    @staticmethod
    def _score_kdj(latest) -> float:
        """Score KDJ position.

        打板视角:
        - J < 0 (超卖区): 反弹机会大, 但首板打板需谨慎 → 60
        - J 20-50 (低位金叉区): 最佳打板区间 → 85-100
        - J 50-80 (正常区): 可操作 → 65-80
        - J > 80 (超买区): 追高风险, 打板谨慎 → 30-50
        - J > 100 (极度超买): 高位接力风险极大 → 10-30
        """
        j = latest.kdj_j

        if j > 100:
            return 15.0
        if j > 80:
            return 40.0
        if j > 50:
            return 75.0
        if j > 20:
            return 90.0
        if j > 0:
            return 65.0
        return 50.0  # 超卖

    @staticmethod
    def _score_rsi(latest) -> float:
        """Score RSI position.

        打板视角:
        - RSI6 < 20: 极度超卖, 反弹概率高但弱势 → 55
        - RSI6 20-40: 偏弱, 首板需更强催化 → 60
        - RSI6 40-60: 中性, 最佳区间 → 80
        - RSI6 60-80: 偏强, 趋势确认 → 75
        - RSI6 > 80: 超买, 追高风险 → 35
        - RSI6 > 90: 极度超买 → 15
        """
        rsi = latest.rsi_6

        if rsi <= 0:
            return 50.0  # No data
        if rsi > 90:
            return 15.0
        if rsi > 80:
            return 35.0
        if rsi > 60:
            return 75.0
        if rsi > 40:
            return 80.0
        if rsi > 20:
            return 60.0
        return 55.0

    @staticmethod
    def _score_boll(latest) -> float:
        """Score BOLL band position.

        打板视角:
        - 价格突破上轨: 强趋势确认 → 85-95
        - 价格在上轨附近: 强势 → 75
        - 价格在中轨上方: 偏强 → 65
        - 价格在中轨下方: 偏弱 → 40
        - 价格在下轨附近: 弱势, 但可能超跌反弹 → 50
        """
        if latest.boll_upper == 0 or latest.boll_mid == 0:
            return 50.0

        close = latest.close
        upper = latest.boll_upper
        mid = latest.boll_mid
        lower = latest.boll_lower

        if close >= upper:
            return 90.0  # Breaking upper band
        if upper > mid:
            # Position ratio within upper half
            ratio = (close - mid) / (upper - mid)
            if ratio > 0.8:
                return 80.0
            if ratio > 0.5:
                return 70.0
            if ratio > 0:
                return 60.0

        # Below mid
        if lower < mid:
            ratio = (close - lower) / (mid - lower)
            if ratio < 0.2:
                return 45.0  # Near lower, possible bounce
            return 40.0

        return 50.0

"""Market context analyzer.

Derives market regime and risk context from index data (上证/创业板指).
Used by sentiment and risk assessment for dynamic threshold adjustment.
"""

import sqlite3
from datetime import date

from hit_astocker.models.index_data import MarketContext
from hit_astocker.repositories.index_repo import IndexDailyRepository

SH_CODE = "000001.SH"  # 上证综指
GEM_CODE = "399006.SZ"  # 创业板指


class MarketContextAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._index_repo = IndexDailyRepository(conn)

    def analyze(self, trade_date: date) -> MarketContext | None:
        """Compute market context from index data. Returns None if data unavailable."""
        sh = self._index_repo.find_by_date_and_code(trade_date, SH_CODE)
        gem = self._index_repo.find_by_date_and_code(trade_date, GEM_CODE)

        if not sh:
            return None

        # Compute MA5 and MA20 for SH index
        sh_bars = self._index_repo.find_recent(SH_CODE, trade_date, count=20)
        sh_ma5_ratio = self._ma_ratio(sh_bars, 5, sh.close)
        sh_ma20_ratio = self._ma_ratio(sh_bars, 20, sh.close)

        # Market regime scoring (-100 to +100)
        regime_score = self._compute_regime_score(
            sh_pct_chg=sh.pct_chg,
            gem_pct_chg=gem.pct_chg if gem else 0.0,
            sh_ma5_ratio=sh_ma5_ratio,
            sh_ma20_ratio=sh_ma20_ratio,
        )

        regime = self._classify_regime(regime_score)

        return MarketContext(
            trade_date=trade_date,
            sh_pct_chg=round(sh.pct_chg, 2),
            gem_pct_chg=round(gem.pct_chg, 2) if gem else 0.0,
            sh_close=sh.close,
            gem_close=gem.close if gem else 0.0,
            sh_ma5_ratio=round(sh_ma5_ratio, 4),
            sh_ma20_ratio=round(sh_ma20_ratio, 4),
            market_regime=regime,
            regime_score=round(regime_score, 2),
        )

    @staticmethod
    def _ma_ratio(bars: list, period: int, current_close: float) -> float:
        """Compute close / MA(period). Returns 1.0 if insufficient data."""
        if len(bars) < period or current_close <= 0:
            return 1.0
        recent = bars[-period:]
        ma = sum(b.close for b in recent) / period
        return current_close / ma if ma > 0 else 1.0

    @staticmethod
    def _compute_regime_score(
        sh_pct_chg: float,
        gem_pct_chg: float,
        sh_ma5_ratio: float,
        sh_ma20_ratio: float,
    ) -> float:
        """
        Compute a regime score from -100 to +100.

        Factors:
        - 今日涨跌幅 (40%): direct signal
        - MA5 位置 (30%): short-term trend
        - MA20 位置 (30%): medium-term trend
        """
        # Today's change score: [-2%, +2%] -> [-100, +100]
        avg_pct = (sh_pct_chg + gem_pct_chg) / 2
        change_score = max(-100, min(100, avg_pct / 2.0 * 100))

        # MA5 position: ratio 1.02 → score +100, ratio 0.98 → score -100
        ma5_score = max(-100, min(100, (sh_ma5_ratio - 1.0) / 0.02 * 100))

        # MA20 position
        ma20_score = max(-100, min(100, (sh_ma20_ratio - 1.0) / 0.03 * 100))

        return 0.40 * change_score + 0.30 * ma5_score + 0.30 * ma20_score

    @staticmethod
    def _classify_regime(score: float) -> str:
        if score >= 50:
            return "STRONG_BULL"
        if score >= 15:
            return "BULL"
        if score >= -15:
            return "NEUTRAL"
        if score >= -50:
            return "BEAR"
        return "STRONG_BEAR"

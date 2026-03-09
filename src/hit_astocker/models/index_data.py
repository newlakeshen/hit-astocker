"""Market index daily data model."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class IndexDaily:
    trade_date: date
    ts_code: str  # 000001.SH (上证), 399006.SZ (创业板指), 399001.SZ (深证成指)
    open: float
    high: float
    low: float
    close: float
    pre_close: float
    pct_chg: float
    vol: float
    amount: float


@dataclass(frozen=True)
class MarketContext:
    """Market-level context derived from index data for risk adjustment."""

    trade_date: date
    sh_pct_chg: float  # 上证涨跌幅
    gem_pct_chg: float  # 创业板涨跌幅
    sh_close: float
    gem_close: float
    # MA position: close relative to MA5/MA20 (>1 = above MA)
    sh_ma5_ratio: float  # close / MA5
    sh_ma20_ratio: float  # close / MA20
    market_regime: str  # STRONG_BULL / BULL / NEUTRAL / BEAR / STRONG_BEAR
    regime_score: float  # -100 to +100, positive = bullish

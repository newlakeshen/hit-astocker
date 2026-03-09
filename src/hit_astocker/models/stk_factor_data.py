"""个股技术因子数据模型."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class StockFactorRecord:
    """日度技术因子."""

    trade_date: date
    ts_code: str
    close: float
    # MACD
    macd_dif: float
    macd_dea: float
    macd: float
    # KDJ
    kdj_k: float
    kdj_d: float
    kdj_j: float
    # RSI
    rsi_6: float
    rsi_12: float
    # BOLL
    boll_upper: float
    boll_mid: float
    boll_lower: float

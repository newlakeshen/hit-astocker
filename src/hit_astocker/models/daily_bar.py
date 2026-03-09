"""Daily bar (K-line) model."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    ts_code: str
    open: float
    high: float
    low: float
    close: float
    pre_close: float
    change: float
    pct_chg: float
    vol: float  # 成交量 (手)
    amount: float  # 成交额 (千元)

    @property
    def amplitude(self) -> float:
        """振幅"""
        if self.pre_close <= 0:
            return 0.0
        return (self.high - self.low) / self.pre_close * 100

    @property
    def upper_shadow_ratio(self) -> float:
        """上影线比例"""
        body_high = max(self.open, self.close)
        if self.high <= body_high or self.pre_close <= 0:
            return 0.0
        return (self.high - body_high) / self.pre_close * 100

    @property
    def lower_shadow_ratio(self) -> float:
        """下影线比例"""
        body_low = min(self.open, self.close)
        if body_low <= self.low or self.pre_close <= 0:
            return 0.0
        return (body_low - self.low) / self.pre_close * 100

    @property
    def volume_amount_million(self) -> float:
        """成交额 (万元)"""
        return self.amount / 10.0

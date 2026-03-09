"""Signal validation model — tracks T+1 performance of trading signals."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SignalValidation:
    """Validation result for a single signal against T+1 daily bar."""

    trade_date: date  # signal date (T)
    next_date: date  # validation date (T+1)
    ts_code: str
    name: str
    signal_score: float  # composite score on signal date
    risk_level: str
    position_hint: str
    signal_close: float  # close price on signal day (buy price)
    # T+1 performance (% relative to signal_close)
    next_open_pct: float  # 开盘溢价率
    next_high_pct: float  # 最高收益率
    next_close_pct: float  # 收盘收益率
    next_low_pct: float  # 最大回撤
    is_win: bool  # next_close_pct > 0
    is_limit_up: bool  # T+1 继续涨停


@dataclass(frozen=True)
class ValidationStats:
    """Aggregate statistics from signal validation."""

    total_signals: int
    validated_count: int  # signals with T+1 data
    win_count: int
    loss_count: int
    hit_rate: float  # win_count / validated_count
    avg_return: float  # mean next_close_pct
    avg_max_return: float  # mean next_high_pct
    avg_max_drawdown: float  # mean next_low_pct
    total_return: float  # sum of next_close_pct (simple P&L proxy)
    max_single_loss: float  # worst single-trade return
    max_single_win: float  # best single-trade return
    consecutive_losses: int  # max consecutive losing trades
    by_risk: dict[str, "RiskBucketStats"]
    by_score_bucket: dict[str, "ScoreBucketStats"]


@dataclass(frozen=True)
class RiskBucketStats:
    """Stats broken down by risk level."""

    risk_level: str
    count: int
    win_count: int
    hit_rate: float
    avg_return: float


@dataclass(frozen=True)
class ScoreBucketStats:
    """Stats broken down by score range."""

    label: str  # e.g., "80-100", "60-80"
    count: int
    win_count: int
    hit_rate: float
    avg_return: float

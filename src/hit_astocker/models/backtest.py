"""Backtest models for realistic board-hitting simulation.

Three execution modes (买入方式):
  AUCTION        — 复盘选股→次日竞价买 (buy at T+1 open)
  WEAK_TO_STRONG — 弱转强开盘买 (buy at T+1 open, only if open < T close)
  RE_SEAL        — 回封买 (buy at T+1 limit-up price after board re-seal)

Exit logic on T+2 (A-share T+1 settlement):
  STOP_LOSS   — 炸板止损
  TAKE_PROFIT — 冲高兑现
  CLOSE       — 尾盘平仓
  YIZI_HELD   — 一字跌停无法卖出
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class ExecutionMode(str, Enum):
    AUCTION = "AUCTION"
    WEAK_TO_STRONG = "WEAK_TO_STRONG"
    RE_SEAL = "RE_SEAL"


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    CLOSE = "CLOSE"
    YIZI_HELD = "YIZI_HELD"


class SkipReason(str, Enum):
    YIZI_CANT_BUY = "YIZI_CANT_BUY"
    NO_WEAKNESS = "NO_WEAKNESS"
    NO_RESEAL = "NO_RESEAL"
    NO_T1_BAR = "NO_T1_BAR"
    NO_T2_BAR = "NO_T2_BAR"


@dataclass(frozen=True)
class BacktestConfig:
    execution_mode: ExecutionMode = ExecutionMode.AUCTION
    stop_loss_pct: float = -7.0
    take_profit_pct: float = 5.0


@dataclass(frozen=True)
class TradeResult:
    """A single executed trade."""

    trade_date: date      # signal date (T)
    entry_date: date      # buy date (T+1)
    exit_date: date       # sell date (T+2)
    ts_code: str
    name: str
    signal_type: str
    signal_score: float
    risk_level: str
    execution_mode: str
    entry_price: float
    exit_price: float
    exit_reason: str
    pnl_pct: float        # (exit - entry) / entry * 100
    t1_open_pct: float    # T+1 open vs T close (%)


@dataclass(frozen=True)
class SkippedSignal:
    """A signal that could not be executed."""

    trade_date: date
    ts_code: str
    name: str
    signal_score: float
    skip_reason: str


@dataclass(frozen=True)
class BacktestDayResult:
    trade_date: date
    trades: tuple[TradeResult, ...]
    skipped: tuple[SkippedSignal, ...]


# ── Aggregate stats ──────────────────────────────────────────────


@dataclass(frozen=True)
class BucketStats:
    """Generic stats for a single bucket (by type / risk / score / exit)."""

    label: str
    count: int
    win_count: int
    hit_rate: float
    avg_pnl: float
    total_pnl: float


@dataclass(frozen=True)
class BacktestStats:
    total_signals: int
    traded_count: int
    skipped_count: int
    win_count: int
    loss_count: int
    hit_rate: float
    avg_pnl: float
    total_pnl: float
    max_win: float
    max_loss: float
    profit_factor: float       # gross_profit / |gross_loss|, inf if no loss
    consecutive_losses: int
    by_exit: dict[str, BucketStats] = field(default_factory=dict)
    by_type: dict[str, BucketStats] = field(default_factory=dict)
    by_risk: dict[str, BucketStats] = field(default_factory=dict)
    by_score: dict[str, BucketStats] = field(default_factory=dict)
    skip_summary: dict[str, int] = field(default_factory=dict)

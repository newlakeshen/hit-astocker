"""Backtest models for realistic board-hitting simulation.

Three execution modes (买入方式):
  AUCTION        — 复盘选股→次日竞价买 (buy at T+1 open)
  WEAK_TO_STRONG — 弱转强开盘买 (buy at T+1 open, only if open < T close)
  RE_SEAL        — 回封买 (buy at T+1 limit-up price after board re-seal)

Friction model:
  滑点 (slippage)        — configurable basis points, applied to entry & exit
  佣金 (commission)      — 万2.5 per side (A-share standard)
  印花税 (stamp duty)    — 千0.5 on sell only
  竞价溢价上限           — skip if T+1 opens too far above T close
  排板成交率             — skip RE_SEAL if turnover too low (queue can't fill)

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
    PREMIUM_TOO_HIGH = "PREMIUM_TOO_HIGH"
    LOW_FILL_RATE = "LOW_FILL_RATE"


@dataclass(frozen=True)
class BacktestConfig:
    execution_mode: ExecutionMode = ExecutionMode.AUCTION
    stop_loss_pct: float = -7.0
    take_profit_pct: float = 5.0
    # ── friction ──
    slippage_bps: float = 10.0              # 滑点 (基点), 单边
    commission_rate: float = 0.00025         # 佣金 (万2.5), 单边
    stamp_duty_rate: float = 0.0005          # 印花税 (千0.5), 仅卖出
    max_open_premium_pct: float = 7.0        # 竞价溢价上限 (%), 超过不追
    min_reseal_turnover: float = 3.0         # 回封最低换手率 (%), 低于则跳过
    # ── 动态止损/止盈 (按信号类型调整, 0=使用默认) ──
    dynamic_stops: bool = True              # 是否启用动态止损/止盈

    def __post_init__(self) -> None:
        if self.stop_loss_pct >= 0:
            raise ValueError(f"stop_loss_pct 必须为负数, 当前: {self.stop_loss_pct}")
        if self.take_profit_pct <= 0:
            raise ValueError(f"take_profit_pct 必须为正数, 当前: {self.take_profit_pct}")

    def effective_stops(self, signal_type: str) -> tuple[float, float]:
        """Return (stop_loss_pct, take_profit_pct) adjusted by signal type.

        打板不同策略的止损逻辑不同:
          首板弱转强: 止损紧(-5%), 弱转强失败通常快速回落
          连板接力:   止盈宽(+8%), 连板股有惯性, 给空间
          龙头空间:   止盈最宽(+10%), 龙头溢价最高
        """
        if not self.dynamic_stops:
            return self.stop_loss_pct, self.take_profit_pct

        if signal_type == "FIRST_BOARD":
            # 首板: 紧止损, 标准止盈
            return max(self.stop_loss_pct, -5.0), self.take_profit_pct
        if signal_type == "FOLLOW_BOARD":
            # 连板: 标准止损, 宽止盈
            return self.stop_loss_pct, max(self.take_profit_pct, 8.0)
        if signal_type == "SECTOR_LEADER":
            # 龙头: 标准止损, 最宽止盈
            return self.stop_loss_pct, max(self.take_profit_pct, 10.0)

        return self.stop_loss_pct, self.take_profit_pct

    def effective_stops_with_regime(
        self, signal_type: str, market_regime: str | None = None,
    ) -> tuple[float, float]:
        """Type-specific stops adjusted by market regime."""
        base_stop, base_target = self.effective_stops(signal_type)

        # dynamic_stops=False -> no regime adjustment either
        if not self.dynamic_stops:
            return base_stop, base_target

        if market_regime is None or market_regime in ("BULL", "NEUTRAL"):
            return base_stop, base_target

        # Regime adjustments (positive = tighter stop / wider take)
        regime_adj = {
            "STRONG_BULL": (1.0, 2.0),   # tighter stop, wider take
            "BEAR": (1.5, -1.0),          # tighter stop, tighter take
            "STRONG_BEAR": (2.0, -2.0),   # most aggressive
        }
        stop_adj, take_adj = regime_adj.get(market_regime, (0.0, 0.0))

        # Tighter stop = less negative (add positive adjustment)
        adj_stop = base_stop + stop_adj
        # Ensure stop doesn't become positive
        adj_stop = min(adj_stop, -1.0)

        # Take profit adjustment
        adj_target = base_target + take_adj
        # Ensure take doesn't become negative
        adj_target = max(adj_target, 1.0)

        return adj_stop, adj_target


@dataclass(frozen=True)
class TradeResult:
    """A single executed trade (net of all friction costs)."""

    trade_date: date      # signal date (T)
    entry_date: date      # buy date (T+1)
    exit_date: date       # sell date (T+2)
    ts_code: str
    name: str
    signal_type: str
    signal_score: float
    risk_level: str
    execution_mode: str
    entry_price: float    # effective entry (after slippage)
    exit_price: float     # effective exit (after slippage)
    exit_reason: str
    pnl_pct: float        # net PnL after all costs
    cost_pct: float       # round-trip friction cost as % of entry
    t1_open_pct: float    # T+1 open vs T close (%)
    cycle_phase: str | None = None    # sentiment cycle phase at signal time
    profit_regime: str | None = None  # profit effect regime at signal time


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
    avg_cost: float            # mean cost_pct per trade
    max_win: float
    max_loss: float
    profit_factor: float       # gross_profit / |gross_loss|, inf if no loss
    consecutive_losses: int
    by_exit: dict[str, BucketStats] = field(default_factory=dict)
    by_type: dict[str, BucketStats] = field(default_factory=dict)
    by_risk: dict[str, BucketStats] = field(default_factory=dict)
    by_score: dict[str, BucketStats] = field(default_factory=dict)
    skip_summary: dict[str, int] = field(default_factory=dict)

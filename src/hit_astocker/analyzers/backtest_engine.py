"""Backtest engine — realistic board-hitting trade simulation.

Simulates three execution modes with proper A-share T+1 settlement:
  T  : signal generated (limit-up stock scored)
  T+1: execute buy (entry)
  T+2: execute sell (exit, earliest possible under T+1 rule)

Entry rules:
  AUCTION        — buy at T+1 open; skip 一字板 (can't buy)
  WEAK_TO_STRONG — buy at T+1 open only if open < T close (gap-down → potential reversal)
  RE_SEAL        — buy at T+1 close (limit-up price) only if T+1 re-sealed (open_times > 0)

Exit rules (T+2, priority order):
  1. 一字跌停 → YIZI_HELD (can't sell, stuck at limit-down)
  2. open gaps through stop  → STOP_LOSS at open
  3. open gaps through target → TAKE_PROFIT at open
  4. low touches stop        → STOP_LOSS at stop_price
  5. high touches target      → TAKE_PROFIT at target_price
  6. both 4 & 5 on same bar  → STOP_LOSS (conservative)
  7. default                  → CLOSE at T+2 close
"""

import sqlite3
from datetime import date

from hit_astocker.models.backtest import (
    BacktestConfig,
    BacktestDayResult,
    BacktestStats,
    BucketStats,
    ExecutionMode,
    ExitReason,
    SkipReason,
    SkippedSignal,
    TradeResult,
)
from hit_astocker.models.daily_bar import DailyBar
from hit_astocker.models.limit_data import LimitDirection, LimitRecord
from hit_astocker.models.signal import TradingSignal
from hit_astocker.repositories.daily_bar_repo import DailyBarRepository
from hit_astocker.repositories.limit_repo import LimitListRepository


class BacktestEngine:
    def __init__(self, conn: sqlite3.Connection):
        self._bar_repo = DailyBarRepository(conn)
        self._limit_repo = LimitListRepository(conn)

    # ── public API ───────────────────────────────────────────────

    def simulate_day(
        self,
        signals: list[TradingSignal],
        config: BacktestConfig,
        trade_date: date,
        entry_date: date,
        exit_date: date,
    ) -> BacktestDayResult:
        """Simulate trades: signals from *trade_date*, buy on *entry_date*, sell on *exit_date*."""
        if not signals:
            return BacktestDayResult(trade_date=trade_date, trades=(), skipped=())

        # Batch-load all bars and limit records
        t_bars = {b.ts_code: b for b in self._bar_repo.find_records_by_date(trade_date)}
        t1_bars = {b.ts_code: b for b in self._bar_repo.find_records_by_date(entry_date)}
        t2_bars = {b.ts_code: b for b in self._bar_repo.find_records_by_date(exit_date)}

        t1_limits = {r.ts_code: r for r in self._limit_repo.find_records_by_date(entry_date)}
        t2_limits = {r.ts_code: r for r in self._limit_repo.find_records_by_date(exit_date)}

        trades: list[TradeResult] = []
        skipped: list[SkippedSignal] = []

        for sig in signals:
            result = self._process_signal(
                sig, config, trade_date, entry_date, exit_date,
                t_bars, t1_bars, t2_bars, t1_limits, t2_limits,
            )
            if isinstance(result, TradeResult):
                trades.append(result)
            else:
                skipped.append(result)

        return BacktestDayResult(
            trade_date=trade_date,
            trades=tuple(trades),
            skipped=tuple(skipped),
        )

    # ── per-signal processing ────────────────────────────────────

    def _process_signal(
        self,
        sig: TradingSignal,
        config: BacktestConfig,
        trade_date: date,
        entry_date: date,
        exit_date: date,
        t_bars: dict[str, DailyBar],
        t1_bars: dict[str, DailyBar],
        t2_bars: dict[str, DailyBar],
        t1_limits: dict[str, LimitRecord],
        t2_limits: dict[str, LimitRecord],
    ) -> TradeResult | SkippedSignal:
        code = sig.ts_code
        t1_bar = t1_bars.get(code)

        if not t1_bar:
            return self._skip(sig, SkipReason.NO_T1_BAR)

        t_bar = t_bars.get(code)
        signal_close = t_bar.close if t_bar and t_bar.close > 0 else t1_bar.pre_close

        t1_limit = t1_limits.get(code)
        is_yizi = (
            t1_limit is not None
            and t1_limit.limit == LimitDirection.UP
            and t1_limit.open_times == 0
        )
        is_reseal = (
            t1_limit is not None
            and t1_limit.limit == LimitDirection.UP
            and t1_limit.open_times > 0
        )

        # ── Determine entry ──
        entry_price = self._determine_entry(
            config.execution_mode, t1_bar, signal_close, is_yizi, is_reseal,
        )
        if entry_price is None:
            reason = self._entry_skip_reason(config.execution_mode, is_yizi, is_reseal, t1_bar, signal_close)
            return self._skip(sig, reason)

        if entry_price <= 0:
            return self._skip(sig, SkipReason.NO_T1_BAR)

        # ── Determine exit ──
        t2_bar = t2_bars.get(code)
        if not t2_bar:
            return self._skip(sig, SkipReason.NO_T2_BAR)

        t2_limit = t2_limits.get(code)
        exit_price, exit_reason = self._determine_exit(entry_price, t2_bar, t2_limit, config)

        pnl_pct = (exit_price - entry_price) / entry_price * 100
        t1_open_pct = (t1_bar.open - signal_close) / signal_close * 100 if signal_close > 0 else 0.0

        return TradeResult(
            trade_date=trade_date,
            entry_date=entry_date,
            exit_date=exit_date,
            ts_code=code,
            name=sig.name,
            signal_type=sig.signal_type.value,
            signal_score=sig.composite_score,
            risk_level=sig.risk_level.value,
            execution_mode=config.execution_mode.value,
            entry_price=round(entry_price, 2),
            exit_price=round(exit_price, 2),
            exit_reason=exit_reason,
            pnl_pct=round(pnl_pct, 2),
            t1_open_pct=round(t1_open_pct, 2),
        )

    # ── Entry logic ──────────────────────────────────────────────

    @staticmethod
    def _determine_entry(
        mode: ExecutionMode,
        t1_bar: DailyBar,
        signal_close: float,
        is_yizi: bool,
        is_reseal: bool,
    ) -> float | None:
        """Return entry price, or None if entry is not possible."""
        if mode == ExecutionMode.AUCTION:
            if is_yizi:
                return None
            return t1_bar.open

        if mode == ExecutionMode.WEAK_TO_STRONG:
            if is_yizi:
                return None
            if t1_bar.open >= signal_close:
                return None  # no weakness shown
            return t1_bar.open

        if mode == ExecutionMode.RE_SEAL:
            if not is_reseal:
                return None  # T+1 didn't break and re-seal
            return t1_bar.close  # limit-up price (re-sealed)

        return None  # unreachable

    @staticmethod
    def _entry_skip_reason(
        mode: ExecutionMode,
        is_yizi: bool,
        is_reseal: bool,
        t1_bar: DailyBar,
        signal_close: float,
    ) -> SkipReason:
        if mode == ExecutionMode.AUCTION:
            return SkipReason.YIZI_CANT_BUY

        if mode == ExecutionMode.WEAK_TO_STRONG:
            if is_yizi:
                return SkipReason.YIZI_CANT_BUY
            return SkipReason.NO_WEAKNESS

        # RE_SEAL
        return SkipReason.NO_RESEAL

    # ── Exit logic ───────────────────────────────────────────────

    @staticmethod
    def _determine_exit(
        entry_price: float,
        t2_bar: DailyBar,
        t2_limit: LimitRecord | None,
        config: BacktestConfig,
    ) -> tuple[float, str]:
        """Return (exit_price, exit_reason)."""
        # 1. 一字跌停: can't sell (no buyers)
        is_yizi_down = (
            t2_limit is not None
            and t2_limit.limit == LimitDirection.DOWN
            and t2_limit.open_times == 0
        )
        if is_yizi_down:
            return t2_bar.close, ExitReason.YIZI_HELD.value

        stop_price = entry_price * (1 + config.stop_loss_pct / 100)
        target_price = entry_price * (1 + config.take_profit_pct / 100)

        # 2. Open gaps through stop/target
        if t2_bar.open <= stop_price:
            return t2_bar.open, ExitReason.STOP_LOSS.value
        if t2_bar.open >= target_price:
            return t2_bar.open, ExitReason.TAKE_PROFIT.value

        stop_hit = t2_bar.low <= stop_price
        target_hit = t2_bar.high >= target_price

        # 3. Both triggered: conservative → stop first
        if stop_hit and target_hit:
            return stop_price, ExitReason.STOP_LOSS.value

        # 4. Only stop
        if stop_hit:
            return stop_price, ExitReason.STOP_LOSS.value

        # 5. Only target
        if target_hit:
            return target_price, ExitReason.TAKE_PROFIT.value

        # 6. Default: close
        return t2_bar.close, ExitReason.CLOSE.value

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _skip(sig: TradingSignal, reason: SkipReason) -> SkippedSignal:
        return SkippedSignal(
            trade_date=sig.trade_date,
            ts_code=sig.ts_code,
            name=sig.name,
            signal_score=sig.composite_score,
            skip_reason=reason.value,
        )


# ── Stats computation ────────────────────────────────────────────


def compute_backtest_stats(
    trades: list[TradeResult],
    skipped: list[SkippedSignal],
    total_signals: int,
) -> BacktestStats:
    """Compute aggregate statistics from trade results."""
    traded = len(trades)
    skipped_count = len(skipped)

    if traded == 0:
        skip_summary = _count_skip_reasons(skipped)
        return BacktestStats(
            total_signals=total_signals,
            traded_count=0,
            skipped_count=skipped_count,
            win_count=0, loss_count=0,
            hit_rate=0.0, avg_pnl=0.0, total_pnl=0.0,
            max_win=0.0, max_loss=0.0,
            profit_factor=0.0,
            consecutive_losses=0,
            skip_summary=skip_summary,
        )

    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return BacktestStats(
        total_signals=total_signals,
        traded_count=traded,
        skipped_count=skipped_count,
        win_count=len(wins),
        loss_count=len(losses),
        hit_rate=len(wins) / traded,
        avg_pnl=sum(pnls) / traded,
        total_pnl=sum(pnls),
        max_win=max(pnls),
        max_loss=min(pnls),
        profit_factor=round(profit_factor, 2),
        consecutive_losses=_max_consecutive_losses(trades),
        by_exit=_stats_by_key(trades, lambda t: t.exit_reason),
        by_type=_stats_by_key(trades, lambda t: t.signal_type),
        by_risk=_stats_by_key(trades, lambda t: t.risk_level),
        by_score=_stats_by_score(trades),
        skip_summary=_count_skip_reasons(skipped),
    )


def _stats_by_key(
    trades: list[TradeResult],
    key_fn,
) -> dict[str, BucketStats]:
    buckets: dict[str, list[TradeResult]] = {}
    for t in trades:
        buckets.setdefault(key_fn(t), []).append(t)

    result = {}
    for label, items in sorted(buckets.items()):
        pnls = [t.pnl_pct for t in items]
        win_count = sum(1 for p in pnls if p > 0)
        result[label] = BucketStats(
            label=label,
            count=len(items),
            win_count=win_count,
            hit_rate=win_count / len(items),
            avg_pnl=round(sum(pnls) / len(items), 2),
            total_pnl=round(sum(pnls), 2),
        )
    return result


def _stats_by_score(trades: list[TradeResult]) -> dict[str, BucketStats]:
    ranges = [("80-100", 80, 101), ("60-80", 60, 80), ("40-60", 40, 60), ("0-40", 0, 40)]
    result = {}
    for label, lo, hi in ranges:
        items = [t for t in trades if lo <= t.signal_score < hi]
        if not items:
            continue
        pnls = [t.pnl_pct for t in items]
        win_count = sum(1 for p in pnls if p > 0)
        result[label] = BucketStats(
            label=label,
            count=len(items),
            win_count=win_count,
            hit_rate=win_count / len(items),
            avg_pnl=round(sum(pnls) / len(items), 2),
            total_pnl=round(sum(pnls), 2),
        )
    return result


def _max_consecutive_losses(trades: list[TradeResult]) -> int:
    sorted_t = sorted(trades, key=lambda t: (t.trade_date, t.ts_code))
    max_streak = current = 0
    for t in sorted_t:
        if t.pnl_pct <= 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def _count_skip_reasons(skipped: list[SkippedSignal]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in skipped:
        counts[s.skip_reason] = counts.get(s.skip_reason, 0) + 1
    return dict(sorted(counts.items()))

"""Backtest engine — realistic board-hitting trade simulation with friction.

Trade lifecycle (A-share T+1 settlement):
  T  : signal generated (limit-up stock scored)
  T+1: execute buy (entry, after slippage)
  T+2: execute sell (exit, after slippage, commissions, stamp duty)

Entry rules:
  AUCTION        — buy at T+1 open; skip 一字板 / 溢价超限
  WEAK_TO_STRONG — buy at T+1 open only if open < T close
  RE_SEAL        — buy at T+1 close only if re-sealed AND turnover >= threshold

Exit rules (T+2, priority order):
  1. 一字跌停 → YIZI_HELD (can't sell, stuck at limit-down)
  2. open gaps through stop  → STOP_LOSS at open
  3. open gaps through target → TAKE_PROFIT at open
  4. low touches stop        → STOP_LOSS at stop_price
  5. high touches target      → TAKE_PROFIT at target_price
  6. both 4 & 5 on same bar  → TAKE_PROFIT (optimistic: 先涨后跌概率更高)
  7. default                  → CLOSE at T+2 close

Friction applied to every trade:
  - Slippage: entry * (1 + bps/10000), exit * (1 - bps/10000)
  - Commission: rate * entry + rate * exit
  - Stamp duty: rate * exit (sell-side only)
"""

import math
import sqlite3
from collections.abc import Callable
from datetime import date

from hit_astocker.models.backtest import (
    BacktestConfig,
    BacktestDayResult,
    BacktestStats,
    BucketStats,
    EquityPoint,
    ExecutionMode,
    ExitReason,
    SkippedSignal,
    SkipReason,
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
        self._bar_cache: dict[date, dict[str, DailyBar]] = {}
        self._limit_cache: dict[date, dict[str, LimitRecord]] = {}

    def _get_bars(self, d: date) -> dict[str, DailyBar]:
        if d not in self._bar_cache:
            self._bar_cache[d] = {b.ts_code: b for b in self._bar_repo.find_records_by_date(d)}
        return self._bar_cache[d]

    def _get_limits(self, d: date) -> dict[str, LimitRecord]:
        if d not in self._limit_cache:
            self._limit_cache[d] = {r.ts_code: r for r in self._limit_repo.find_records_by_date(d)}
        return self._limit_cache[d]

    def evict_stale_cache(self, keep_after: date) -> None:
        """Remove cached entries older than *keep_after* to bound memory."""
        for cache in (self._bar_cache, self._limit_cache):
            stale = [d for d in cache if d < keep_after]
            for d in stale:
                del cache[d]

    # ── public API ───────────────────────────────────────────────

    def simulate_day(
        self,
        signals: list[TradingSignal],
        config: BacktestConfig,
        trade_date: date,
        entry_date: date,
        exit_date: date,
        *,
        exit_date_t3: date | None = None,
        market_regime: str | None = None,
        cycle_phase: str | None = None,
    ) -> BacktestDayResult:
        """Simulate trades: signals from *trade_date*, buy on *entry_date*, sell on *exit_date*.

        When exit_date_t3 is provided and a signal's effective_hold_days == 2,
        positions that would otherwise close at T+2 (CLOSE) are extended to T+3.
        Stop loss on T+2 still triggers immediately (protection first).
        """
        if not signals:
            return BacktestDayResult(trade_date=trade_date, trades=(), skipped=())

        # Batch-load bars and limit records (with caching across days)
        t_bars = self._get_bars(trade_date)
        t1_bars = self._get_bars(entry_date)
        t2_bars = self._get_bars(exit_date)

        t1_limits = self._get_limits(entry_date)
        t2_limits = self._get_limits(exit_date)

        t3_bars: dict[str, DailyBar] | None = None
        t3_limits: dict[str, LimitRecord] | None = None
        if exit_date_t3:
            t3_bars = self._get_bars(exit_date_t3)
            t3_limits = self._get_limits(exit_date_t3)

        trades: list[TradeResult] = []
        skipped: list[SkippedSignal] = []

        for sig in signals:
            hold_days = config.effective_hold_days(
                sig.signal_type.value,
                cycle_phase,
            )
            result = self._process_signal(
                sig,
                config,
                trade_date,
                entry_date,
                exit_date,
                t_bars,
                t1_bars,
                t2_bars,
                t1_limits,
                t2_limits,
                market_regime=market_regime,
                hold_days=hold_days,
                exit_date_t3=exit_date_t3,
                t3_bars=t3_bars,
                t3_limits=t3_limits,
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
        *,
        market_regime: str | None = None,
        hold_days: int = 1,
        exit_date_t3: date | None = None,
        t3_bars: dict[str, DailyBar] | None = None,
        t3_limits: dict[str, LimitRecord] | None = None,
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
            t1_limit is not None and t1_limit.limit == LimitDirection.UP and t1_limit.open_times > 0
        )

        # ── Determine raw entry price ──
        raw_entry = self._determine_entry(
            config.execution_mode,
            t1_bar,
            signal_close,
            is_yizi,
            is_reseal,
        )
        if raw_entry is None:
            reason = self._entry_skip_reason(
                config.execution_mode,
                is_yizi,
                is_reseal,
                t1_bar,
                signal_close,
            )
            return self._skip(sig, reason)

        if raw_entry <= 0:
            return self._skip(sig, SkipReason.NO_T1_BAR)

        # ── Open premium filter (AUCTION / WEAK_TO_STRONG) ──
        if config.execution_mode in (ExecutionMode.AUCTION, ExecutionMode.WEAK_TO_STRONG):
            if signal_close > 0:
                open_prem = (t1_bar.open - signal_close) / signal_close * 100
                if open_prem > config.max_open_premium_pct:
                    return self._skip(sig, SkipReason.PREMIUM_TOO_HIGH)

        # ── Fill rate filter (RE_SEAL: low turnover → queue can't fill) ──
        if config.execution_mode == ExecutionMode.RE_SEAL:
            if t1_limit and t1_limit.turnover_ratio < config.min_reseal_turnover:
                return self._skip(sig, SkipReason.LOW_FILL_RATE)

        # ── Apply slippage to entry ──
        slip = config.slippage_bps / 10000
        eff_entry = raw_entry * (1 + slip)

        # ── Determine raw exit (with dynamic stops) ──
        t2_bar = t2_bars.get(code)
        if not t2_bar:
            return self._skip(sig, SkipReason.NO_T2_BAR)

        t2_limit = t2_limits.get(code)
        eff_stop, eff_target = config.effective_stops_with_regime(
            sig.signal_type.value,
            market_regime,
        )
        raw_exit, exit_reason = self._determine_exit(
            eff_entry,
            t2_bar,
            t2_limit,
            config,
            eff_stop,
            eff_target,
        )

        # ── T+3 延长持仓: T+2 未触发止损/止盈 → 继续持有到 T+3 ──
        actual_exit_date = exit_date
        if (
            hold_days >= 2
            and exit_reason == ExitReason.CLOSE.value
            and exit_date_t3 is not None
            and t3_bars is not None
        ):
            t3_bar = t3_bars.get(code)
            t3_limit = t3_limits.get(code) if t3_limits else None
            if t3_bar:
                raw_exit, exit_reason = self._determine_exit(
                    eff_entry,
                    t3_bar,
                    t3_limit,
                    config,
                    eff_stop,
                    eff_target,
                )
                actual_exit_date = exit_date_t3

        # ── Apply slippage to exit ──
        # 一字跌停 (YIZI_HELD) 时无法卖出, 不扣出场滑点和卖出成本
        is_yizi_held = exit_reason == ExitReason.YIZI_HELD.value
        eff_exit = raw_exit if is_yizi_held else raw_exit * (1 - slip)

        # ── Compute costs ──
        buy_comm = eff_entry * config.commission_rate
        if is_yizi_held:
            sell_comm = 0.0
            stamp = 0.0
        else:
            sell_comm = eff_exit * config.commission_rate
            stamp = eff_exit * config.stamp_duty_rate
        total_cost = buy_comm + sell_comm + stamp
        cost_pct = total_cost / eff_entry * 100 if eff_entry > 0 else 0.0

        # ── Net PnL ──
        gross_pnl_pct = (eff_exit - eff_entry) / eff_entry * 100 if eff_entry > 0 else 0.0
        net_pnl_pct = gross_pnl_pct - cost_pct

        t1_open_pct = (t1_bar.open - signal_close) / signal_close * 100 if signal_close > 0 else 0.0

        return TradeResult(
            trade_date=trade_date,
            entry_date=entry_date,
            exit_date=actual_exit_date,
            ts_code=code,
            name=sig.name,
            signal_type=sig.signal_type.value,
            signal_score=sig.composite_score,
            risk_level=sig.risk_level.value,
            execution_mode=config.execution_mode.value,
            entry_price=round(eff_entry, 2),
            exit_price=round(eff_exit, 2),
            exit_reason=exit_reason,
            pnl_pct=round(net_pnl_pct, 2),
            cost_pct=round(cost_pct, 2),
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
        """Return raw entry price, or None if entry is not possible."""
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
        eff_stop_pct: float | None = None,
        eff_target_pct: float | None = None,
    ) -> tuple[float, str]:
        """Return (raw_exit_price, exit_reason). Slippage applied by caller."""
        # 1. 一字跌停: can't sell (no buyers)
        is_yizi_down = (
            t2_limit is not None
            and t2_limit.limit == LimitDirection.DOWN
            and t2_limit.open_times == 0
        )
        if is_yizi_down:
            return t2_bar.close, ExitReason.YIZI_HELD.value

        stop_pct = eff_stop_pct if eff_stop_pct is not None else config.stop_loss_pct
        target_pct = eff_target_pct if eff_target_pct is not None else config.take_profit_pct
        stop_price = entry_price * (1 + stop_pct / 100)
        target_price = entry_price * (1 + target_pct / 100)

        # 2. Open gaps through stop/target
        if t2_bar.open <= stop_price:
            return t2_bar.open, ExitReason.STOP_LOSS.value
        if t2_bar.open >= target_price:
            return t2_bar.open, ExitReason.TAKE_PROFIT.value

        stop_hit = t2_bar.low <= stop_price
        target_hit = t2_bar.high >= target_price

        # 3. Both triggered on same bar → take profit (先涨后跌概率更高)
        if stop_hit and target_hit:
            return target_price, ExitReason.TAKE_PROFIT.value

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
    trading_days: list[date] | None = None,
    num_slots: int = 5,
) -> BacktestStats:
    """Compute aggregate statistics from trade results.

    When *trading_days* is provided, also computes return metrics:
    equity curve, Sharpe/Sortino ratios, max drawdown, CAGR, monthly/yearly returns.

    *num_slots*: number of equal-weight capital slots (default=signal_top_k).
    Each trade uses 1/num_slots of capital. Affects equity curve compounding.
    """
    traded = len(trades)
    skipped_count = len(skipped)

    if traded == 0:
        return BacktestStats(
            total_signals=total_signals,
            traded_count=0,
            skipped_count=skipped_count,
            win_count=0,
            loss_count=0,
            hit_rate=0.0,
            avg_pnl=0.0,
            total_pnl=0.0,
            avg_cost=0.0,
            max_win=0.0,
            max_loss=0.0,
            profit_factor=float("nan"),
            consecutive_losses=0,
            skip_summary=_count_skip_reasons(skipped),
        )

    pnls = [t.pnl_pct for t in trades]
    costs = [t.cost_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Return metrics (equity curve, Sharpe, drawdown, etc.)
    return_kwargs = _compute_return_metrics(trades, trading_days, num_slots) if trading_days else {}

    return BacktestStats(
        total_signals=total_signals,
        traded_count=traded,
        skipped_count=skipped_count,
        win_count=len(wins),
        loss_count=len(losses),
        hit_rate=len(wins) / traded,
        avg_pnl=sum(pnls) / traded,
        total_pnl=sum(pnls),
        avg_cost=sum(costs) / traded,
        max_win=max(pnls),
        max_loss=min(pnls),
        profit_factor=round(profit_factor, 2),
        consecutive_losses=_max_consecutive_losses(trades),
        by_exit=_stats_by_key(trades, lambda t: t.exit_reason),
        by_type=_stats_by_key(trades, lambda t: t.signal_type),
        by_risk=_stats_by_key(trades, lambda t: t.risk_level),
        by_score=_stats_by_score(trades),
        skip_summary=_count_skip_reasons(skipped),
        **return_kwargs,
    )


def _stats_by_key(
    trades: list[TradeResult],
    key_fn: Callable[[TradeResult], str],
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


# ── Return metrics computation ───────────────────────────────────


def _compute_return_metrics(
    trades: list[TradeResult],
    trading_days: list[date],
    num_slots: int = 5,
) -> dict[str, object]:
    """Compute equity curve, risk-adjusted returns, monthly/yearly breakdowns.

    Returns a dict of keyword args to merge into BacktestStats.

    Equity model: equal-weight fixed-slot portfolio.
    - *num_slots* capital slots (default 5 = signal_top_k), each uses 1/K of capital
    - Group trades by exit_date (PnL realized on exit)
    - Daily portfolio return = sum(pnl_pct) / num_slots
      (not mean — accounts for partial capital deployment on light days)
    - Equity compounds: equity *= (1 + daily_return / 100)
    - Sharpe/Sortino assume rf=0 (appropriate for short-term board-hitting)
    - Sortino uses standard downside deviation (denominator=N, target=0)
    """
    if not trades:
        return {}

    num_slots = max(1, num_slots)

    # ── Build daily returns (grouped by exit_date) ──
    # Portfolio return = sum(per-trade returns) / num_slots
    # Each trade uses 1/num_slots of capital; unused slots earn 0%
    daily_pnls: dict[date, list[float]] = {}
    for t in trades:
        daily_pnls.setdefault(t.exit_date, []).append(t.pnl_pct)

    daily_returns: dict[date, float] = {d: sum(pnls) / num_slots for d, pnls in daily_pnls.items()}

    # ── Equity curve (compound over all trading days in range) ──
    equity = 100.0
    peak = 100.0
    curve: list[EquityPoint] = []
    max_dd = 0.0
    best_dd_start: date | None = None
    best_dd_end: date | None = None
    peak_date: date = trading_days[0] if trading_days else trades[0].exit_date

    for d in trading_days:
        day_ret = daily_returns.get(d, 0.0)
        equity *= 1 + day_ret / 100
        if equity > peak:
            peak = equity
            peak_date = d
        dd = (equity - peak) / peak * 100  # negative
        if dd < max_dd:
            max_dd = dd
            best_dd_start = peak_date
            best_dd_end = d
        curve.append(
            EquityPoint(
                trade_date=d,
                equity=round(equity, 4),
                daily_return=round(day_ret, 4),
                drawdown=round(dd, 4),
            )
        )

    # ── Annualized return (CAGR) ──
    n_days = len(trading_days)
    total_years = n_days / 252.0  # trading days per year
    final_equity = equity
    if total_years > 0 and final_equity > 0:
        cagr = (final_equity / 100.0) ** (1.0 / total_years) - 1.0
        annualized_return = cagr * 100.0
    else:
        annualized_return = 0.0

    # ── Volatility & Sharpe/Sortino (from daily returns including 0-days, rf=0) ──
    all_daily = [daily_returns.get(d, 0.0) for d in trading_days]
    n = len(all_daily)
    mean_ret = sum(all_daily) / n if n > 0 else 0.0

    if n > 1:
        var = sum((r - mean_ret) ** 2 for r in all_daily) / (n - 1)
        std = math.sqrt(var)
        annualized_vol = std * math.sqrt(252)

        sharpe = (mean_ret / std * math.sqrt(252)) if std > 0 else 0.0

        # Sortino: downside deviation (target=0, denominator=N per standard definition)
        downside_var = sum(min(r, 0.0) ** 2 for r in all_daily) / n
        downside_std = math.sqrt(downside_var)
        sortino = (mean_ret / downside_std * math.sqrt(252)) if downside_std > 0 else 0.0
    else:
        annualized_vol = 0.0
        sharpe = 0.0
        sortino = 0.0

    # ── Calmar = CAGR / |max_drawdown| (preserves sign for directional meaning) ──
    calmar = annualized_return / abs(max_dd) if max_dd < 0 else 0.0

    # ── Win streak ──
    sorted_trades = sorted(trades, key=lambda t: (t.trade_date, t.ts_code))
    win_streak = _max_consecutive_wins(sorted_trades)

    # ── Monthly / Yearly breakdowns ──
    by_month = _stats_by_key(trades, lambda t: t.exit_date.strftime("%Y-%m"))
    by_year = _stats_by_key(trades, lambda t: t.exit_date.strftime("%Y"))

    # Downsample equity curve: keep one point per month (last trading day)
    # to avoid storing thousands of points
    monthly_curve: dict[str, EquityPoint] = {}
    for pt in curve:
        key = pt.trade_date.strftime("%Y-%m")
        monthly_curve[key] = pt  # keep last day of each month

    return {
        "annualized_return": round(annualized_return, 2),
        "annualized_volatility": round(annualized_vol, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_start": best_dd_start,
        "max_drawdown_end": best_dd_end,
        "calmar_ratio": round(calmar, 2),
        "win_streak": win_streak,
        "by_month": by_month,
        "by_year": by_year,
        "equity_curve": tuple(monthly_curve.values()),
    }


def _max_consecutive_wins(trades: list[TradeResult]) -> int:
    max_streak = current = 0
    for t in trades:
        if t.pnl_pct > 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak

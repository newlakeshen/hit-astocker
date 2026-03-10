"""Signal validation engine.

Validates trading signals against T+1 daily bar data to compute
actual P&L, hit rates, and factor attribution.
"""

import sqlite3
from datetime import date

from hit_astocker.models.signal import TradingSignal
from hit_astocker.models.validation import (
    RiskBucketStats,
    ScoreBucketStats,
    SignalValidation,
    ValidationStats,
)
from hit_astocker.repositories.daily_bar_repo import DailyBarRepository


class SignalValidator:
    def __init__(self, conn: sqlite3.Connection):
        self._bar_repo = DailyBarRepository(conn)

    def validate_signals(
        self, signals: list[TradingSignal], next_date: date
    ) -> list[SignalValidation]:
        """Validate a list of signals against T+1 daily bars."""
        if not signals:
            return []

        # Batch-load T+1 bars
        next_bars = {b.ts_code: b for b in self._bar_repo.find_records_by_date(next_date)}
        # Load signal-day bars for close price
        signal_date = signals[0].trade_date
        signal_bars = {b.ts_code: b for b in self._bar_repo.find_records_by_date(signal_date)}

        validations = []
        for sig in signals:
            signal_bar = signal_bars.get(sig.ts_code)
            next_bar = next_bars.get(sig.ts_code)

            if not signal_bar or not next_bar or signal_bar.close <= 0:
                continue

            close = signal_bar.close
            next_open_pct = (next_bar.open - close) / close * 100
            next_high_pct = (next_bar.high - close) / close * 100
            next_close_pct = (next_bar.close - close) / close * 100
            next_low_pct = (next_bar.low - close) / close * 100

            # Detect T+1 limit-up: pct_chg >= 9.5% for main board, >=19.5% for GEM/STAR
            limit_threshold = 19.5 if sig.ts_code.startswith(("30", "68")) else 9.5
            is_limit_up = next_bar.pct_chg >= limit_threshold

            validations.append(SignalValidation(
                trade_date=signal_date,
                next_date=next_date,
                ts_code=sig.ts_code,
                name=sig.name,
                signal_score=sig.composite_score,
                risk_level=sig.risk_level.value,
                position_hint=sig.position_hint,
                signal_close=close,
                next_open_pct=round(next_open_pct, 2),
                next_high_pct=round(next_high_pct, 2),
                next_close_pct=round(next_close_pct, 2),
                next_low_pct=round(next_low_pct, 2),
                is_win=next_close_pct > 0,
                is_limit_up=is_limit_up,
            ))

        return validations

    @staticmethod
    def compute_stats(validations: list[SignalValidation], total_signals: int) -> ValidationStats:
        """Compute aggregate statistics from validation results."""
        validated = len(validations)
        if validated == 0:
            return ValidationStats(
                total_signals=total_signals,
                validated_count=0,
                win_count=0, loss_count=0,
                hit_rate=0.0, avg_return=0.0,
                avg_max_return=0.0, avg_max_drawdown=0.0,
                total_return=0.0,
                max_single_loss=0.0, max_single_win=0.0,
                consecutive_losses=0,
                by_risk={}, by_score_bucket={},
            )

        wins = [v for v in validations if v.is_win]
        losses = [v for v in validations if not v.is_win]
        returns = [v.next_close_pct for v in validations]
        max_returns = [v.next_high_pct for v in validations]
        drawdowns = [v.next_low_pct for v in validations]

        # Consecutive losses
        max_consecutive = _max_consecutive_losses(validations)

        # By risk level
        by_risk = _stats_by_risk(validations)

        # By score bucket
        by_score = _stats_by_score(validations)

        return ValidationStats(
            total_signals=total_signals,
            validated_count=validated,
            win_count=len(wins),
            loss_count=len(losses),
            hit_rate=len(wins) / validated,
            avg_return=sum(returns) / validated,
            avg_max_return=sum(max_returns) / validated,
            avg_max_drawdown=sum(drawdowns) / validated,
            total_return=sum(returns),
            max_single_loss=min(returns),
            max_single_win=max(returns),
            consecutive_losses=max_consecutive,
            by_risk=by_risk,
            by_score_bucket=by_score,
        )


def _max_consecutive_losses(validations: list[SignalValidation]) -> int:
    """Find the longest streak of consecutive losing trades."""
    # Sort by date then code for deterministic ordering
    sorted_v = sorted(validations, key=lambda v: (v.trade_date, v.ts_code))
    max_streak = 0
    current_streak = 0
    for v in sorted_v:
        if not v.is_win:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak


def _stats_by_risk(validations: list[SignalValidation]) -> dict[str, RiskBucketStats]:
    """Compute stats grouped by risk level."""
    buckets: dict[str, list[SignalValidation]] = {}
    for v in validations:
        buckets.setdefault(v.risk_level, []).append(v)

    result = {}
    for risk, items in sorted(buckets.items()):
        wins = sum(1 for v in items if v.is_win)
        avg_ret = sum(v.next_close_pct for v in items) / len(items)
        result[risk] = RiskBucketStats(
            risk_level=risk,
            count=len(items),
            win_count=wins,
            hit_rate=wins / len(items),
            avg_return=round(avg_ret, 2),
        )
    return result


def _stats_by_score(validations: list[SignalValidation]) -> dict[str, ScoreBucketStats]:
    """Compute stats grouped by score range."""
    score_ranges = [
        ("80-100", 80, 101),
        ("60-80", 60, 80),
        ("40-60", 40, 60),
        ("0-40", 0, 40),
    ]
    result = {}
    for label, low, high in score_ranges:
        items = [v for v in validations if low <= v.signal_score < high]
        if not items:
            continue
        wins = sum(1 for v in items if v.is_win)
        avg_ret = sum(v.next_close_pct for v in items) / len(items)
        result[label] = ScoreBucketStats(
            label=label,
            count=len(items),
            win_count=wins,
            hit_rate=wins / len(items),
            avg_return=round(avg_ret, 2),
        )
    return result

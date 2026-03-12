# src/hit_astocker/analyzers/backtest_diagnosis.py
"""6-dimensional backtest diagnosis analyzer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hit_astocker.models.backtest import TradeResult

__all__ = ["BacktestDiagnosis", "SliceStats"]


@dataclass(frozen=True)
class SliceStats:
    """Statistics for one slice of trades."""

    count: int
    win_count: int
    hit_rate: float
    avg_pnl: float
    total_pnl: float
    max_win: float
    max_loss: float
    profit_loss_ratio: float  # avg_win / |avg_loss|, inf if no loss

    @staticmethod
    def from_trades(trades: list[TradeResult]) -> SliceStats:
        if not trades:
            return SliceStats(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        pnls = [t.pnl_pct for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        count = len(trades)
        win_count = len(wins)
        hit_rate = round(win_count / count * 100, 1) if count else 0.0
        avg_pnl = round(sum(pnls) / count, 2) if count else 0.0
        total_pnl = round(sum(pnls), 2)
        max_win = round(max(pnls), 2) if pnls else 0.0
        max_loss = round(min(pnls), 2) if pnls else 0.0

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        pl_ratio = round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else float("inf")

        return SliceStats(
            count=count,
            win_count=win_count,
            hit_rate=hit_rate,
            avg_pnl=avg_pnl,
            total_pnl=total_pnl,
            max_win=max_win,
            max_loss=max_loss,
            profit_loss_ratio=pl_ratio,
        )


def _score_bucket(score: float) -> str:
    if score < 50:
        return "<50"
    if score < 60:
        return "50-60"
    if score < 70:
        return "60-70"
    if score < 80:
        return "70-80"
    return "80+"


class BacktestDiagnosis:
    """Slice backtest trades along 6 dimensions."""

    def __init__(self, trades: list[TradeResult]) -> None:
        self._trades = trades

    def _group_and_stat(
        self, key_fn: Callable[[TradeResult], str],
    ) -> dict[str, SliceStats]:
        groups: dict[str, list[TradeResult]] = {}
        for t in self._trades:
            k = key_fn(t)
            groups.setdefault(k, []).append(t)
        return {k: SliceStats.from_trades(v) for k, v in groups.items()}

    def slice_by_year(self) -> dict[str, SliceStats]:
        return self._group_and_stat(lambda t: str(t.trade_date.year))

    def slice_by_cycle(self) -> dict[str, SliceStats]:
        return self._group_and_stat(lambda t: t.cycle_phase or "UNKNOWN")

    def slice_by_signal_type(self) -> dict[str, SliceStats]:
        return self._group_and_stat(lambda t: t.signal_type)

    def slice_by_exit_reason(self) -> dict[str, SliceStats]:
        return self._group_and_stat(lambda t: t.exit_reason)

    def slice_by_score(self) -> dict[str, SliceStats]:
        return self._group_and_stat(lambda t: _score_bucket(t.signal_score))

    def slice_by_profit_regime(self) -> dict[str, SliceStats]:
        return self._group_and_stat(lambda t: t.profit_regime or "UNKNOWN")

    def all_slices(self) -> dict[str, dict[str, SliceStats]]:
        return {
            "year": self.slice_by_year(),
            "cycle": self.slice_by_cycle(),
            "signal_type": self.slice_by_signal_type(),
            "exit_reason": self.slice_by_exit_reason(),
            "score": self.slice_by_score(),
            "profit_regime": self.slice_by_profit_regime(),
        }

    def find_bleeding_points(self, threshold: float = 0.20) -> list[dict]:
        """Find slices that contribute >threshold of total loss."""
        total_loss = sum(t.pnl_pct for t in self._trades if t.pnl_pct < 0)
        if total_loss >= 0:
            return []

        bleeds: list[dict] = []
        for dim_name, slices in self.all_slices().items():
            for key, stats in slices.items():
                if stats.total_pnl >= 0:
                    continue
                contribution = stats.total_pnl / total_loss
                if contribution >= threshold:
                    bleeds.append({
                        "dimension": dim_name,
                        "slice_key": key,
                        "total_pnl": stats.total_pnl,
                        "contribution_pct": round(contribution * 100, 1),
                        "count": stats.count,
                        "hit_rate": stats.hit_rate,
                    })

        return sorted(bleeds, key=lambda b: b["total_pnl"])

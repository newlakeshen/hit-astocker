"""Tests for backtest engine return metrics computation."""

from datetime import date

import pytest

from hit_astocker.analyzers.backtest_engine import (
    _compute_return_metrics,
    _max_consecutive_wins,
    compute_backtest_stats,
)
from hit_astocker.models.backtest import TradeResult


def _make_trade(
    exit_date: date,
    pnl_pct: float,
    trade_date: date | None = None,
) -> TradeResult:
    """Helper to create a TradeResult with minimal required fields."""
    td = trade_date or exit_date
    return TradeResult(
        trade_date=td,
        entry_date=td,
        exit_date=exit_date,
        ts_code="000001.SZ",
        name="测试",
        signal_type="FIRST_BOARD",
        signal_score=70.0,
        risk_level="MEDIUM",
        execution_mode="AUCTION",
        entry_price=10.0,
        exit_price=10.0 * (1 + pnl_pct / 100),
        exit_reason="CLOSE",
        pnl_pct=pnl_pct,
        cost_pct=0.1,
        t1_open_pct=1.0,
    )


class TestComputeReturnMetrics:
    """Tests for _compute_return_metrics."""

    def test_empty_trades_returns_empty(self):
        result = _compute_return_metrics([], [date(2025, 1, 2)])
        assert result == {}

    def test_single_winning_trade(self):
        trades = [_make_trade(date(2025, 1, 3), 5.0)]
        trading_days = [date(2025, 1, 2), date(2025, 1, 3)]
        # num_slots=1 for single-trade tests (full capital per trade)
        result = _compute_return_metrics(trades, trading_days, num_slots=1)

        # Equity: 100 * 1.0 * 1.05 = 105.0
        assert result["annualized_return"] > 0
        assert result["sharpe_ratio"] > 0
        assert result["max_drawdown_pct"] == 0.0  # never below peak
        assert result["win_streak"] == 1

    def test_single_losing_trade(self):
        trades = [_make_trade(date(2025, 1, 3), -5.0)]
        trading_days = [date(2025, 1, 2), date(2025, 1, 3)]
        result = _compute_return_metrics(trades, trading_days, num_slots=1)

        assert result["annualized_return"] < 0
        assert result["sharpe_ratio"] < 0
        assert result["max_drawdown_pct"] < 0

    def test_equity_curve_compounds_correctly(self):
        """Two trades on different days: equity should compound.

        With num_slots=1, each trade uses 100% capital (single-position model).
        Equity curve is downsampled to monthly snapshots (last day per month).
        """
        trades = [
            _make_trade(date(2025, 1, 3), 10.0, trade_date=date(2025, 1, 2)),
            _make_trade(date(2025, 1, 6), -5.0, trade_date=date(2025, 1, 3)),
        ]
        trading_days = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)]
        result = _compute_return_metrics(trades, trading_days, num_slots=1)

        curve = result["equity_curve"]
        # Monthly downsample: only last day of January kept (Jan 6)
        assert len(curve) == 1
        # 100 * 1.10 * 0.95 = 104.5
        assert curve[0].equity == pytest.approx(104.5, abs=0.01)
        assert curve[0].trade_date == date(2025, 1, 6)

    def test_max_drawdown_tracks_correctly(self):
        """Peak at +10%, then drops to -5% net → drawdown from peak."""
        trades = [
            _make_trade(date(2025, 1, 3), 10.0, trade_date=date(2025, 1, 2)),
            _make_trade(date(2025, 1, 6), -10.0, trade_date=date(2025, 1, 3)),
        ]
        trading_days = [
            date(2025, 1, 2),
            date(2025, 1, 3),
            date(2025, 1, 6),
        ]
        result = _compute_return_metrics(trades, trading_days, num_slots=1)

        # Peak = 110, valley = 110 * 0.9 = 99 → drawdown = (99-110)/110 = -10%
        assert result["max_drawdown_pct"] == pytest.approx(-10.0, abs=0.1)
        assert result["max_drawdown_start"] == date(2025, 1, 3)
        assert result["max_drawdown_end"] == date(2025, 1, 6)

    def test_all_winning_trades(self):
        trades = [
            _make_trade(date(2025, 1, 3), 3.0),
            _make_trade(date(2025, 1, 6), 2.0),
            _make_trade(date(2025, 1, 7), 4.0),
        ]
        trading_days = [date(2025, 1, 3), date(2025, 1, 6), date(2025, 1, 7)]
        result = _compute_return_metrics(trades, trading_days, num_slots=1)

        assert result["max_drawdown_pct"] == 0.0
        assert result["calmar_ratio"] == 0.0  # no drawdown → 0
        assert result["win_streak"] == 3

    def test_calmar_preserves_sign(self):
        """Negative CAGR should produce negative Calmar."""
        trades = [
            _make_trade(date(2025, 1, 3), -8.0),
            _make_trade(date(2025, 1, 6), -5.0),
        ]
        trading_days = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)]
        result = _compute_return_metrics(trades, trading_days, num_slots=1)

        assert result["calmar_ratio"] < 0  # negative CAGR / |max_dd|

    def test_monthly_and_yearly_buckets(self):
        trades = [
            _make_trade(date(2025, 1, 10), 5.0),
            _make_trade(date(2025, 2, 15), -3.0),
        ]
        trading_days = [date(2025, 1, 10), date(2025, 2, 15)]
        result = _compute_return_metrics(trades, trading_days)

        assert "2025-01" in result["by_month"]
        assert "2025-02" in result["by_month"]
        assert "2025" in result["by_year"]
        assert result["by_month"]["2025-01"].total_pnl == 5.0
        assert result["by_month"]["2025-02"].total_pnl == -3.0

    def test_same_day_multiple_trades_slot_weighted(self):
        """Two trades closing same day, 5 slots → daily return = sum(pnl) / 5."""
        trades = [
            _make_trade(date(2025, 1, 3), 10.0),
            _make_trade(date(2025, 1, 3), -4.0),
        ]
        trading_days = [date(2025, 1, 2), date(2025, 1, 3)]
        result = _compute_return_metrics(trades, trading_days, num_slots=5)

        curve = result["equity_curve"]
        equities = {pt.trade_date: pt.equity for pt in curve}
        # sum(10, -4) / 5 = 1.2% → 100 * 1.012 = 101.2
        assert equities[date(2025, 1, 3)] == pytest.approx(101.2, abs=0.01)

    def test_num_slots_dilutes_returns(self):
        """With more slots, each trade has less impact on portfolio."""
        trades = [_make_trade(date(2025, 1, 3), -10.0)]
        trading_days = [date(2025, 1, 2), date(2025, 1, 3)]

        # 1 slot (full capital): -10%
        r1 = _compute_return_metrics(trades, trading_days, num_slots=1)
        # 5 slots (20% capital): -10% / 5 = -2%
        r5 = _compute_return_metrics(trades, trading_days, num_slots=5)

        assert r1["equity_curve"][-1].equity == pytest.approx(90.0, abs=0.01)
        assert r5["equity_curve"][-1].equity == pytest.approx(98.0, abs=0.01)


class TestMaxConsecutiveWins:
    def test_empty(self):
        assert _max_consecutive_wins([]) == 0

    def test_all_wins(self):
        trades = [_make_trade(date(2025, 1, d), 1.0) for d in range(3, 8)]
        assert _max_consecutive_wins(trades) == 5

    def test_mixed(self):
        pnls = [1.0, 2.0, -1.0, 3.0, 4.0, 5.0, -2.0]
        trades = [_make_trade(date(2025, 1, 3 + i), p) for i, p in enumerate(pnls)]
        assert _max_consecutive_wins(trades) == 3


class TestComputeBacktestStatsWithTradingDays:
    """Test that compute_backtest_stats integrates return metrics when trading_days provided."""

    def test_without_trading_days_no_return_metrics(self):
        trades = [_make_trade(date(2025, 1, 3), 5.0)]
        stats = compute_backtest_stats(trades, [], 1)
        assert stats.sharpe_ratio == 0.0
        assert stats.equity_curve == ()

    def test_with_trading_days_has_return_metrics(self):
        trades = [_make_trade(date(2025, 1, 3), 5.0)]
        trading_days = [date(2025, 1, 2), date(2025, 1, 3)]
        stats = compute_backtest_stats(trades, [], 1, trading_days)
        assert stats.annualized_return != 0.0
        assert len(stats.equity_curve) > 0
        assert stats.sharpe_ratio != 0.0

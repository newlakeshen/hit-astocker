# tests/unit/models/test_backtest_model.py
from datetime import date
from hit_astocker.models.backtest import TradeResult


def test_trade_result_has_cycle_phase_field():
    """TradeResult should accept optional cycle_phase."""
    tr = TradeResult(
        trade_date=date(2024, 1, 2),
        entry_date=date(2024, 1, 3),
        exit_date=date(2024, 1, 4),
        ts_code="000001.SZ",
        name="平安银行",
        signal_type="FIRST_BOARD",
        signal_score=72.0,
        risk_level="LOW",
        execution_mode="AUCTION",
        entry_price=10.0,
        exit_price=10.5,
        exit_reason="CLOSE",
        pnl_pct=4.5,
        cost_pct=0.15,
        t1_open_pct=1.0,
        cycle_phase="FERMENT",
        profit_regime="NORMAL",
    )
    assert tr.cycle_phase == "FERMENT"
    assert tr.profit_regime == "NORMAL"


def test_trade_result_defaults_none():
    """New fields should default to None for backward compat."""
    tr = TradeResult(
        trade_date=date(2024, 1, 2),
        entry_date=date(2024, 1, 3),
        exit_date=date(2024, 1, 4),
        ts_code="000001.SZ",
        name="平安银行",
        signal_type="FIRST_BOARD",
        signal_score=72.0,
        risk_level="LOW",
        execution_mode="AUCTION",
        entry_price=10.0,
        exit_price=10.5,
        exit_reason="CLOSE",
        pnl_pct=4.5,
        cost_pct=0.15,
        t1_open_pct=1.0,
    )
    assert tr.cycle_phase is None
    assert tr.profit_regime is None

# tests/unit/analyzers/test_backtest_diagnosis.py
from datetime import date
from hit_astocker.models.backtest import TradeResult
from hit_astocker.analyzers.backtest_diagnosis import BacktestDiagnosis


def _make_trade(
    year: int = 2024,
    pnl: float = 1.0,
    signal_type: str = "FIRST_BOARD",
    exit_reason: str = "CLOSE",
    score: float = 70.0,
    cycle_phase: str | None = "FERMENT",
    profit_regime: str | None = "NORMAL",
) -> TradeResult:
    """Helper to create a TradeResult with sensible defaults."""
    return TradeResult(
        trade_date=date(year, 6, 1),
        entry_date=date(year, 6, 2),
        exit_date=date(year, 6, 3),
        ts_code="000001.SZ",
        name="Test",
        signal_type=signal_type,
        signal_score=score,
        risk_level="LOW",
        execution_mode="AUCTION",
        entry_price=10.0,
        exit_price=10.0 * (1 + pnl / 100),
        exit_reason=exit_reason,
        pnl_pct=pnl,
        cost_pct=0.15,
        t1_open_pct=1.0,
        cycle_phase=cycle_phase,
        profit_regime=profit_regime,
    )


def test_slice_by_year():
    trades = [
        _make_trade(year=2023, pnl=5.0),
        _make_trade(year=2023, pnl=-3.0),
        _make_trade(year=2024, pnl=-2.0),
    ]
    diag = BacktestDiagnosis(trades)
    result = diag.slice_by_year()

    assert "2023" in result
    assert "2024" in result
    assert result["2023"].count == 2
    assert result["2023"].win_count == 1
    assert result["2024"].count == 1
    assert result["2024"].win_count == 0


def test_slice_by_cycle():
    trades = [
        _make_trade(cycle_phase="FERMENT", pnl=5.0),
        _make_trade(cycle_phase="RETREAT", pnl=-8.0),
        _make_trade(cycle_phase="RETREAT", pnl=-3.0),
        _make_trade(cycle_phase=None, pnl=1.0),
    ]
    diag = BacktestDiagnosis(trades)
    result = diag.slice_by_cycle()

    assert result["FERMENT"].count == 1
    assert result["RETREAT"].count == 2
    assert result["UNKNOWN"].count == 1


def test_slice_by_signal_type():
    trades = [
        _make_trade(signal_type="FIRST_BOARD", pnl=-2.0),
        _make_trade(signal_type="FIRST_BOARD", pnl=3.0),
        _make_trade(signal_type="SECTOR_LEADER", pnl=8.0),
    ]
    diag = BacktestDiagnosis(trades)
    result = diag.slice_by_signal_type()

    assert result["FIRST_BOARD"].count == 2
    assert result["SECTOR_LEADER"].count == 1


def test_slice_by_exit_reason():
    trades = [
        _make_trade(exit_reason="STOP_LOSS", pnl=-7.0),
        _make_trade(exit_reason="TAKE_PROFIT", pnl=5.0),
        _make_trade(exit_reason="CLOSE", pnl=-1.0),
    ]
    diag = BacktestDiagnosis(trades)
    result = diag.slice_by_exit_reason()

    assert "STOP_LOSS" in result
    assert "TAKE_PROFIT" in result
    assert "CLOSE" in result


def test_slice_by_score_bucket():
    trades = [
        _make_trade(score=45.0, pnl=-5.0),
        _make_trade(score=55.0, pnl=-2.0),
        _make_trade(score=72.0, pnl=3.0),
        _make_trade(score=85.0, pnl=6.0),
    ]
    diag = BacktestDiagnosis(trades)
    result = diag.slice_by_score()

    assert "<50" in result
    assert result["<50"].count == 1
    assert "70-80" in result
    assert result["70-80"].count == 1
    assert "80+" in result
    assert result["80+"].count == 1


def test_slice_by_profit_regime():
    trades = [
        _make_trade(profit_regime="STRONG", pnl=5.0),
        _make_trade(profit_regime="WEAK", pnl=-4.0),
        _make_trade(profit_regime=None, pnl=1.0),
    ]
    diag = BacktestDiagnosis(trades)
    result = diag.slice_by_profit_regime()

    assert result["STRONG"].count == 1
    assert result["WEAK"].count == 1
    assert result["UNKNOWN"].count == 1


def test_all_slices_returns_6_dimensions():
    trades = [_make_trade(), _make_trade(pnl=-2.0)]
    diag = BacktestDiagnosis(trades)
    all_s = diag.all_slices()

    assert set(all_s.keys()) == {
        "year", "cycle", "signal_type", "exit_reason", "score", "profit_regime",
    }


def test_bleeding_points():
    """bleeding_points should identify slices contributing >20% of total loss."""
    trades = [
        _make_trade(cycle_phase="RETREAT", pnl=-10.0),
        _make_trade(cycle_phase="RETREAT", pnl=-8.0),
        _make_trade(cycle_phase="FERMENT", pnl=2.0),
        _make_trade(cycle_phase="CLIMAX", pnl=-1.0),
    ]
    diag = BacktestDiagnosis(trades)
    bleeds = diag.find_bleeding_points()

    # RETREAT total_pnl=-18, total loss=-19, contribution=94.7% > 20%
    retreat_found = any(
        b["slice_key"] == "RETREAT" and b["dimension"] == "cycle"
        for b in bleeds
    )
    assert retreat_found

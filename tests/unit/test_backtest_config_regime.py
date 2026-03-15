# tests/unit/test_backtest_config_regime.py
"""Tests for market-regime adaptive stops (unified -5% stop-loss)."""
from hit_astocker.models.backtest import BacktestConfig


def test_effective_stops_with_regime_strong_bull():
    """STRONG_BULL: wider stop (-0.5%), wider take (+2%)."""
    config = BacktestConfig(stop_loss_pct=-5.0, take_profit_pct=5.0)
    stop, target = config.effective_stops_with_regime("FIRST_BOARD", "STRONG_BULL")
    # FIRST_BOARD: dynamic stop = -5, then STRONG_BULL -0.5 = -5.5
    # take = max(5.0, 8.0) = 8.0, then STRONG_BULL +2 = 10.0
    assert stop == -5.5
    assert target == 10.0


def test_effective_stops_with_regime_bear():
    """BEAR: tighter stop (+1.5), tighter take (-1)."""
    config = BacktestConfig(stop_loss_pct=-5.0, take_profit_pct=5.0)
    stop, target = config.effective_stops_with_regime("FIRST_BOARD", "BEAR")
    # FIRST_BOARD: -5, BEAR +1.5 = -3.5
    # take = max(5.0, 8.0) = 8.0, BEAR -1 = 7.0
    assert stop == -3.5
    assert target == 7.0


def test_effective_stops_with_regime_none_defaults():
    """None regime should use standard effective_stops."""
    config = BacktestConfig(stop_loss_pct=-5.0, take_profit_pct=5.0)
    stop1, target1 = config.effective_stops_with_regime("FIRST_BOARD", None)
    stop2, target2 = config.effective_stops("FIRST_BOARD")
    assert stop1 == stop2
    assert target1 == target2


def test_effective_stops_with_regime_strong_bear():
    """STRONG_BEAR: most aggressive tightening."""
    config = BacktestConfig(stop_loss_pct=-5.0, take_profit_pct=5.0)
    stop, target = config.effective_stops_with_regime("SECTOR_LEADER", "STRONG_BEAR")
    # SECTOR_LEADER: effective_stops -> stop=-5, take=max(5,12)=12
    # STRONG_BEAR: stop=-5+2=-3, take=12+(-2)=10
    assert stop == -3.0
    assert target == 10.0


def test_effective_stops_with_regime_dynamic_stops_false():
    """When dynamic_stops=False, regime adjustments should also be disabled."""
    config = BacktestConfig(stop_loss_pct=-5.0, take_profit_pct=5.0, dynamic_stops=False)
    stop, target = config.effective_stops_with_regime("FIRST_BOARD", "STRONG_BULL")
    # dynamic_stops=False -> raw values, no regime adjustment
    assert stop == -5.0
    assert target == 5.0


def test_unified_stop_loss_all_types():
    """All signal types should use -5% stop-loss."""
    config = BacktestConfig()
    for sig_type in ("FIRST_BOARD", "FOLLOW_BOARD", "SECTOR_LEADER"):
        stop, _ = config.effective_stops(sig_type)
        assert stop == -5.0, f"{sig_type} stop should be -5%, got {stop}"

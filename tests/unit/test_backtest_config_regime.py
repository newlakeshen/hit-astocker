# tests/unit/test_backtest_config_regime.py
"""Tests for market-regime adaptive stops (Phase 2 section 2.3)."""
from hit_astocker.models.backtest import BacktestConfig


def test_effective_stops_with_regime_strong_bull():
    """STRONG_BULL: tighter stop (-1%), wider take (+2%)."""
    config = BacktestConfig(stop_loss_pct=-7.0, take_profit_pct=5.0)
    stop, target = config.effective_stops_with_regime("FIRST_BOARD", "STRONG_BULL")
    # FIRST_BOARD: dynamic stop = max(-7, -5) = -5, then STRONG_BULL +1 = -4
    # take = 5.0, then STRONG_BULL +2 = 7.0
    assert stop == -4.0
    assert target == 7.0


def test_effective_stops_with_regime_bear():
    """BEAR: tighter stop (+1.5), tighter take (-1)."""
    config = BacktestConfig(stop_loss_pct=-7.0, take_profit_pct=5.0)
    stop, target = config.effective_stops_with_regime("FIRST_BOARD", "BEAR")
    # FIRST_BOARD: -5, BEAR +1.5 = -3.5
    # take = 5.0, BEAR -1 = 4.0
    assert stop == -3.5
    assert target == 4.0


def test_effective_stops_with_regime_none_defaults():
    """None regime should use standard effective_stops."""
    config = BacktestConfig(stop_loss_pct=-7.0, take_profit_pct=5.0)
    stop1, target1 = config.effective_stops_with_regime("FIRST_BOARD", None)
    stop2, target2 = config.effective_stops("FIRST_BOARD")
    assert stop1 == stop2
    assert target1 == target2


def test_effective_stops_with_regime_strong_bear():
    """STRONG_BEAR: most aggressive tightening."""
    config = BacktestConfig(stop_loss_pct=-7.0, take_profit_pct=5.0)
    stop, target = config.effective_stops_with_regime("SECTOR_LEADER", "STRONG_BEAR")
    # SECTOR_LEADER: effective_stops -> stop=-7, take=max(5,10)=10
    # STRONG_BEAR: stop=-7+2=-5, take=10+(-2)=8
    assert stop == -5.0
    assert target == 8.0


def test_effective_stops_with_regime_dynamic_stops_false():
    """When dynamic_stops=False, regime adjustments should also be disabled."""
    config = BacktestConfig(stop_loss_pct=-7.0, take_profit_pct=5.0, dynamic_stops=False)
    stop, target = config.effective_stops_with_regime("FIRST_BOARD", "STRONG_BULL")
    # dynamic_stops=False -> raw values, no regime adjustment
    assert stop == -7.0
    assert target == 5.0

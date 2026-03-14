# tests/unit/signals/test_signal_generator.py
"""Tests for _dynamic_min_score (v16: relaxed thresholds)."""

from unittest.mock import MagicMock

from hit_astocker.models.sentiment_cycle import CyclePhase
from hit_astocker.signals.signal_generator import _dynamic_min_score


def _make_sentiment(market_regime: str | None = None):
    """Build a minimal SentimentScore mock."""
    s = MagicMock()
    if market_regime:
        s.market_context.market_regime = market_regime
    else:
        s.market_context = None
    return s


def _make_cycle(phase: CyclePhase, score_delta: float = 0.0):
    """Build a minimal SentimentCycle mock."""
    c = MagicMock()
    c.phase = phase
    c.score_delta = score_delta
    return c


class TestClimaxLateStageThreshold:
    """CLIMAX late-stage (score_delta < -1) adds +5 (v16: relaxed from +8)."""

    def test_climax_delta_minus2_adds_5(self):
        """CLIMAX with delta=-2 → threshold increases by 5."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=-2.0)
        result = _dynamic_min_score(base, sentiment, cycle)
        # base=50, regime NEUTRAL=+0, CLIMAX late=+5 → 55
        assert result == 55.0

    def test_climax_delta_positive_no_adjustment(self):
        """CLIMAX with delta=+2 → no CLIMAX adjustment (early CLIMAX)."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=2.0)
        result = _dynamic_min_score(base, sentiment, cycle)
        # base=50, regime NEUTRAL=+0, no cycle adj → 50
        assert result == 50.0

    def test_climax_delta_minus0_5_no_adjustment(self):
        """CLIMAX with delta=-0.5 (> -1) → no CLIMAX adjustment."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=-0.5)
        result = _dynamic_min_score(base, sentiment, cycle)
        assert result == 50.0

    def test_climax_late_with_bear_regime(self):
        """CLIMAX late + BEAR regime → both adjustments stack."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="BEAR")
        cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=-3.0)
        result = _dynamic_min_score(base, sentiment, cycle)
        # base=50, BEAR=+3, CLIMAX late=+5 → 58
        assert result == 58.0


class TestDynamicMinScoreV16:
    """Test relaxed v16 penalty adjustments."""

    def test_ice_retreat_adds_5(self):
        """ICE/RETREAT adds +5 (v16: relaxed from +8)."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        for phase in (CyclePhase.ICE, CyclePhase.RETREAT):
            cycle = _make_cycle(phase)
            assert _dynamic_min_score(base, sentiment, cycle) == 55.0

    def test_diverge_adds_3(self):
        """DIVERGE adds +3 (v16: relaxed from +5)."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        cycle = _make_cycle(CyclePhase.DIVERGE)
        assert _dynamic_min_score(base, sentiment, cycle) == 53.0

    def test_repair_no_penalty(self):
        """REPAIR adds 0 (v16: removed +3 penalty, encourages participation)."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        cycle = _make_cycle(CyclePhase.REPAIR)
        assert _dynamic_min_score(base, sentiment, cycle) == 50.0

    def test_ferment_subtracts_3(self):
        """FERMENT subtracts 3 (v16: increased from -2)."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        cycle = _make_cycle(CyclePhase.FERMENT)
        assert _dynamic_min_score(base, sentiment, cycle) == 47.0

    def test_strong_bear_adds_5(self):
        """STRONG_BEAR adds +5 (v16: relaxed from +8)."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="STRONG_BEAR")
        assert _dynamic_min_score(base, sentiment, None) == 55.0

    def test_weak_profit_adds_3(self):
        """WEAK profit regime adds +3 (v16: relaxed from +5)."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        assert _dynamic_min_score(base, sentiment, None, profit_regime="WEAK") == 53.0

    def test_clamp_max_65(self):
        """Result clamped to max 65 (v16: lowered from 75)."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="STRONG_BEAR")
        cycle = _make_cycle(CyclePhase.ICE)  # +5 + +5 = 60 (base 50 + 10 = 60)
        result = _dynamic_min_score(base, sentiment, cycle, profit_regime="WEAK")
        # 50 + 5(SB) + 5(ICE) + 3(WEAK) = 63 → clamped to 63 (below 65 cap)
        assert result == 63.0

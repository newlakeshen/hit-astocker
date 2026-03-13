# tests/unit/signals/test_signal_generator.py
"""Tests for _dynamic_min_score CLIMAX late-stage threshold change."""
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
    """CLIMAX late-stage (score_delta < -1) now adds +8 instead of old +3."""

    def test_climax_delta_minus2_adds_8(self):
        """CLIMAX with delta=-2 → threshold increases by 8."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=-2.0)
        result = _dynamic_min_score(base, sentiment, cycle)
        # base=50, regime NEUTRAL=+0, CLIMAX late=+8 → 58
        assert result == 58.0

    def test_climax_delta_minus1_point5_adds_8(self):
        """CLIMAX with delta=-1.5 (< -1) → threshold increases by 8."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="NEUTRAL")
        cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=-1.5)
        result = _dynamic_min_score(base, sentiment, cycle)
        assert result == 58.0

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
        # delta=-0.5 is >= -1, so no CLIMAX late-stage adjustment
        assert result == 50.0

    def test_climax_late_with_bear_regime(self):
        """CLIMAX late + BEAR regime → both adjustments stack."""
        base = 50.0
        sentiment = _make_sentiment(market_regime="BEAR")
        cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=-3.0)
        result = _dynamic_min_score(base, sentiment, cycle)
        # base=50, BEAR=+5, CLIMAX late=+8 → 63
        assert result == 63.0

"""Tests for dynamic signal quota (v16: relaxed for more signal generation)."""

from hit_astocker.signals.signal_generator import _dynamic_top_k


def test_strong_ferment_full_quota():
    """STRONG + FERMENT → full base (5)."""
    assert _dynamic_top_k("STRONG", "FERMENT", score_delta=1.0) == 5


def test_strong_climax_early_full_quota():
    """STRONG + CLIMAX (delta>0) → full base (5)."""
    assert _dynamic_top_k("STRONG", "CLIMAX", score_delta=2.0) == 5


def test_strong_climax_late_reduced():
    """CLIMAX with declining score → reduced to 2."""
    assert _dynamic_top_k("STRONG", "CLIMAX", score_delta=-2.0) == 2


def test_normal_ferment_full():
    """NORMAL + FERMENT → full base (5)."""
    assert _dynamic_top_k("NORMAL", "FERMENT", score_delta=0.0) == 5


def test_normal_other_moderate():
    """NORMAL + non-FERMENT → 3 (v16: relaxed from 1)."""
    assert _dynamic_top_k("NORMAL", "REPAIR", score_delta=0.0) == 3


def test_weak_allows_2():
    """WEAK → 2 (v16: relaxed from 1)."""
    assert _dynamic_top_k("WEAK", "FERMENT", score_delta=1.0) == 2


def test_frozen_allows_1():
    """FROZEN → 1 (v16: relaxed from 0, allow strongest signal)."""
    assert _dynamic_top_k("FROZEN", "FERMENT", score_delta=0.0) == 1


def test_unknown_regime_defaults_to_3():
    """When regime is None/UNKNOWN → 3 (v16: relaxed from 1)."""
    assert _dynamic_top_k(None, "FERMENT", score_delta=0.0) == 3

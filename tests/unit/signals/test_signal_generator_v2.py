"""Tests for dynamic signal quota (Phase 2 section 2.2)."""
from hit_astocker.signals.signal_generator import _dynamic_top_k


def test_strong_ferment_full_quota():
    assert _dynamic_top_k("STRONG", "FERMENT", score_delta=1.0) == 2


def test_strong_climax_early_full_quota():
    assert _dynamic_top_k("STRONG", "CLIMAX", score_delta=2.0) == 2


def test_strong_climax_late_reduced():
    """CLIMAX with declining score -> reduced."""
    assert _dynamic_top_k("STRONG", "CLIMAX", score_delta=-2.0) == 1


def test_normal_ferment_full():
    assert _dynamic_top_k("NORMAL", "FERMENT", score_delta=0.0) == 2


def test_normal_other_reduced():
    assert _dynamic_top_k("NORMAL", "REPAIR", score_delta=0.0) == 1


def test_weak_always_1():
    assert _dynamic_top_k("WEAK", "FERMENT", score_delta=1.0) == 1


def test_frozen_zero():
    assert _dynamic_top_k("FROZEN", "FERMENT", score_delta=0.0) == 0


def test_unknown_regime_defaults_to_1():
    """When regime is None/UNKNOWN, default to 1."""
    assert _dynamic_top_k(None, "FERMENT", score_delta=0.0) == 1

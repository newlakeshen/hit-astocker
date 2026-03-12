"""Tests for tightened cycle gating (Phase 2 section 2.1)."""

from unittest.mock import MagicMock

# _cycle_gate is a module-level function, NOT a method on RiskAssessor
from hit_astocker.models.sentiment_cycle import CyclePhase
from hit_astocker.signals.risk_assessor import _cycle_gate


def _make_candidate(signal_type: str = "FIRST_BOARD", score: float = 70.0):
    """Create a mock ScoredCandidate."""
    c = MagicMock()
    c.signal_type = signal_type
    c.score = score  # ScoredCandidate uses 'score' not 'composite_score'
    return c


def _make_cycle(phase: str, score_delta: float = 0.0, score_accel: float = 0.0):
    """Create a mock SentimentCycle."""
    cycle = MagicMock()
    cycle.phase = CyclePhase(phase)
    cycle.score_delta = score_delta
    cycle.score_accel = score_accel
    return cycle


def test_diverge_blocks_first_board():
    """DIVERGE should block ALL first-board signals (NO_GO)."""
    candidate = _make_candidate("FIRST_BOARD", score=90.0)
    cycle = _make_cycle("DIVERGE")
    result = _cycle_gate(candidate, cycle)
    assert result.value == "NO_GO"


def test_diverge_follow_board_min_75():
    """DIVERGE: FOLLOW_BOARD needs score >= 75."""
    candidate = _make_candidate("FOLLOW_BOARD", score=70.0)
    cycle = _make_cycle("DIVERGE")
    result = _cycle_gate(candidate, cycle)
    assert result.value == "NO_GO"

    candidate_high = _make_candidate("FOLLOW_BOARD", score=76.0)
    result_high = _cycle_gate(candidate_high, cycle)
    assert result_high.value in ("HIGH", "MEDIUM")


def test_diverge_sector_leader_min_80():
    """DIVERGE: SECTOR_LEADER needs score >= 80."""
    candidate = _make_candidate("SECTOR_LEADER", score=75.0)
    cycle = _make_cycle("DIVERGE")
    result = _cycle_gate(candidate, cycle)
    assert result.value == "NO_GO"

    candidate_high = _make_candidate("SECTOR_LEADER", score=82.0)
    result_high = _cycle_gate(candidate_high, cycle)
    assert result_high.value != "NO_GO"


def test_climax_late_raises_threshold():
    """CLIMAX with score_accel < -3 should raise risk.

    Behavior change: current code checks score_delta < -3, new code checks score_accel < -3.
    """
    candidate = _make_candidate("FIRST_BOARD", score=55.0)
    cycle = _make_cycle("CLIMAX", score_delta=-1.0, score_accel=-4.0)
    result = _cycle_gate(candidate, cycle)
    assert result.value in ("HIGH", "NO_GO")


def test_repair_early_only_allows_leader():
    """Early REPAIR (score_delta > 0): only SECTOR_LEADER 80+ passes."""
    cycle = _make_cycle("REPAIR", score_delta=2.0)

    fb = _make_candidate("FIRST_BOARD", score=75.0)
    result_fb = _cycle_gate(fb, cycle)
    assert result_fb.value == "NO_GO"

    follow = _make_candidate("FOLLOW_BOARD", score=80.0)
    result_follow = _cycle_gate(follow, cycle)
    assert result_follow.value == "NO_GO"

    leader_low = _make_candidate("SECTOR_LEADER", score=70.0)
    result_ll = _cycle_gate(leader_low, cycle)
    assert result_ll.value == "NO_GO"

    leader_high = _make_candidate("SECTOR_LEADER", score=82.0)
    result_lh = _cycle_gate(leader_high, cycle)
    assert result_lh.value != "NO_GO"

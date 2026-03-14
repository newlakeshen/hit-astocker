"""Tests for cycle gating (v16: relaxed thresholds for more signal generation)."""

from unittest.mock import MagicMock

# _cycle_gate is a module-level function, NOT a method on RiskAssessor
from hit_astocker.models.sentiment_cycle import CyclePhase
from hit_astocker.signals.risk_assessor import _cycle_gate


def _make_candidate(
    signal_type: str = "FIRST_BOARD",
    score: float = 70.0,
    factors: dict | None = None,
):
    """Create a mock ScoredCandidate."""
    c = MagicMock()
    c.signal_type = signal_type
    c.score = score  # ScoredCandidate uses 'score' not 'composite_score'
    c.factors = factors or {}
    return c


def _make_cycle(phase: str, score_delta: float = 0.0, score_accel: float = 0.0):
    """Create a mock SentimentCycle."""
    cycle = MagicMock()
    cycle.phase = CyclePhase(phase)
    cycle.score_delta = score_delta
    cycle.score_accel = score_accel
    return cycle


def test_diverge_blocks_first_board_no_factors():
    """DIVERGE should block first-board with no factors (NO_GO)."""
    candidate = _make_candidate("FIRST_BOARD", score=90.0, factors={})
    cycle = _make_cycle("DIVERGE")
    result = _cycle_gate(candidate, cycle)
    assert result.value == "NO_GO"


def test_diverge_first_board_whitelist():
    """DIVERGE: FIRST_BOARD score>=65 with sq>=60 OR th>=60 → HIGH."""
    candidate = _make_candidate(
        "FIRST_BOARD",
        score=75.0,
        factors={"seal_quality": 80, "theme_heat": 80},
    )
    cycle = _make_cycle("DIVERGE")
    result = _cycle_gate(candidate, cycle)
    assert result.value == "HIGH"


def test_diverge_first_board_whitelist_one_strong_factor():
    """DIVERGE: FIRST_BOARD with only ONE factor >= 60 → HIGH (v16: OR logic)."""
    candidate = _make_candidate(
        "FIRST_BOARD",
        score=70.0,
        factors={"seal_quality": 65, "theme_heat": 40},
    )
    cycle = _make_cycle("DIVERGE")
    result = _cycle_gate(candidate, cycle)
    assert result.value == "HIGH"


def test_diverge_first_board_both_factors_weak():
    """DIVERGE: FIRST_BOARD with both factors < 60 → NO_GO."""
    candidate = _make_candidate(
        "FIRST_BOARD",
        score=75.0,
        factors={"seal_quality": 50, "theme_heat": 50},
    )
    cycle = _make_cycle("DIVERGE")
    result = _cycle_gate(candidate, cycle)
    assert result.value == "NO_GO"


def test_diverge_follow_board_min_65():
    """DIVERGE: FOLLOW_BOARD needs score >= 65 (v16: relaxed from 75)."""
    candidate_low = _make_candidate("FOLLOW_BOARD", score=60.0)
    cycle = _make_cycle("DIVERGE")
    assert _cycle_gate(candidate_low, cycle).value == "NO_GO"

    candidate_high = _make_candidate("FOLLOW_BOARD", score=66.0)
    assert _cycle_gate(candidate_high, cycle).value in ("HIGH", "MEDIUM")


def test_diverge_sector_leader_min_70():
    """DIVERGE: SECTOR_LEADER needs score >= 70 (v16: relaxed from 80)."""
    candidate_low = _make_candidate("SECTOR_LEADER", score=65.0)
    cycle = _make_cycle("DIVERGE")
    assert _cycle_gate(candidate_low, cycle).value == "NO_GO"

    candidate_high = _make_candidate("SECTOR_LEADER", score=72.0)
    assert _cycle_gate(candidate_high, cycle).value != "NO_GO"


def test_climax_late_raises_threshold():
    """CLIMAX with score_accel < -3 should raise risk."""
    candidate = _make_candidate("FIRST_BOARD", score=55.0)
    cycle = _make_cycle("CLIMAX", score_delta=-1.0, score_accel=-4.0)
    result = _cycle_gate(candidate, cycle)
    assert result.value in ("HIGH", "NO_GO")


def test_repair_early_allows_high_score():
    """Early REPAIR (score_delta > 0): score>=65 → MEDIUM, <65 → HIGH."""
    cycle = _make_cycle("REPAIR", score_delta=2.0)

    # score < 65 → HIGH (not NO_GO)
    fb = _make_candidate("FIRST_BOARD", score=60.0)
    assert _cycle_gate(fb, cycle).value == "HIGH"

    # score >= 65 → MEDIUM
    fb_high = _make_candidate("FIRST_BOARD", score=70.0)
    assert _cycle_gate(fb_high, cycle).value == "MEDIUM"

    leader_high = _make_candidate("SECTOR_LEADER", score=82.0)
    assert _cycle_gate(leader_high, cycle).value == "MEDIUM"


def test_retreat_relaxed_thresholds():
    """RETREAT: 龙头/连板 65+ → HIGH, 首板 70+ → HIGH, lower → NO_GO."""
    cycle = _make_cycle("RETREAT")

    # FIRST_BOARD score=70 → HIGH (v16: relaxed from NO_GO)
    fb = _make_candidate("FIRST_BOARD", score=70.0)
    assert _cycle_gate(fb, cycle).value == "HIGH"

    # FIRST_BOARD score=60 → NO_GO (still below threshold)
    fb_low = _make_candidate("FIRST_BOARD", score=60.0)
    assert _cycle_gate(fb_low, cycle).value == "NO_GO"

    # SECTOR_LEADER 65+ → HIGH (v16: relaxed from 75)
    leader = _make_candidate("SECTOR_LEADER", score=65.0)
    assert _cycle_gate(leader, cycle).value == "HIGH"

    follow = _make_candidate("FOLLOW_BOARD", score=65.0)
    assert _cycle_gate(follow, cycle).value == "HIGH"


def test_ice_relaxed_thresholds():
    """ICE: score>=60 → HIGH (v16: relaxed from 70)."""
    cycle = _make_cycle("ICE")

    fb_60 = _make_candidate("FIRST_BOARD", score=60.0)
    assert _cycle_gate(fb_60, cycle).value == "HIGH"

    fb_low = _make_candidate("FIRST_BOARD", score=55.0)
    assert _cycle_gate(fb_low, cycle).value == "NO_GO"

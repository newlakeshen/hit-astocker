"""Tests for tightened cycle gating (Phase 2 section 2.1)."""

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


def test_diverge_blocks_first_board_default():
    """DIVERGE should block first-board with weak factors (NO_GO)."""
    candidate = _make_candidate("FIRST_BOARD", score=90.0, factors={})
    cycle = _make_cycle("DIVERGE")
    result = _cycle_gate(candidate, cycle)
    assert result.value == "NO_GO"


def test_diverge_first_board_whitelist():
    """DIVERGE: FIRST_BOARD with strong core factors → HIGH (not NO_GO)."""
    candidate = _make_candidate(
        "FIRST_BOARD", score=75.0,
        factors={"seal_quality": 80, "theme_heat": 80},
    )
    cycle = _make_cycle("DIVERGE")
    result = _cycle_gate(candidate, cycle)
    assert result.value == "HIGH"


def test_diverge_first_board_whitelist_insufficient():
    """DIVERGE: FIRST_BOARD with one weak core factor → still NO_GO."""
    candidate = _make_candidate(
        "FIRST_BOARD", score=75.0,
        factors={"seal_quality": 80, "theme_heat": 50},  # theme_heat too low
    )
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
    """CLIMAX with score_accel < -3 should raise risk."""
    candidate = _make_candidate("FIRST_BOARD", score=55.0)
    cycle = _make_cycle("CLIMAX", score_delta=-1.0, score_accel=-4.0)
    result = _cycle_gate(candidate, cycle)
    assert result.value in ("HIGH", "NO_GO")


def test_repair_early_allows_high_score():
    """Early REPAIR (score_delta > 0): score>=65 → MEDIUM, <65 → HIGH."""
    cycle = _make_cycle("REPAIR", score_delta=2.0)

    # score < 65 → HIGH (not NO_GO anymore)
    fb = _make_candidate("FIRST_BOARD", score=60.0)
    result_fb = _cycle_gate(fb, cycle)
    assert result_fb.value == "HIGH"

    # score >= 65 → MEDIUM
    fb_high = _make_candidate("FIRST_BOARD", score=70.0)
    result_high = _cycle_gate(fb_high, cycle)
    assert result_high.value == "MEDIUM"

    leader_high = _make_candidate("SECTOR_LEADER", score=82.0)
    result_lh = _cycle_gate(leader_high, cycle)
    assert result_lh.value == "MEDIUM"


def test_retreat_allows_high_score_leader():
    """RETREAT: SECTOR_LEADER/FOLLOW_BOARD 75+ → HIGH, others → NO_GO."""
    cycle = _make_cycle("RETREAT")

    fb = _make_candidate("FIRST_BOARD", score=80.0)
    assert _cycle_gate(fb, cycle).value == "NO_GO"

    leader = _make_candidate("SECTOR_LEADER", score=75.0)
    assert _cycle_gate(leader, cycle).value == "HIGH"

    follow = _make_candidate("FOLLOW_BOARD", score=75.0)
    assert _cycle_gate(follow, cycle).value == "HIGH"


def test_ice_allows_moderate_score():
    """ICE: score>=70 → HIGH (relaxed from 80)."""
    cycle = _make_cycle("ICE")

    fb_70 = _make_candidate("FIRST_BOARD", score=70.0)
    assert _cycle_gate(fb_70, cycle).value == "HIGH"

    fb_low = _make_candidate("FIRST_BOARD", score=65.0)
    assert _cycle_gate(fb_low, cycle).value == "NO_GO"

"""Tests for risk assessor."""

from datetime import date

from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.sentiment_cycle import CyclePhase, SentimentCycle
from hit_astocker.models.signal import RiskLevel
from hit_astocker.signals.composite_scorer import ScoredCandidate
from hit_astocker.signals.risk_assessor import RiskAssessor, _cycle_gate


def _make_sentiment(score: float, broken_rate: float = 0.1) -> SentimentScore:
    return SentimentScore(
        trade_date=date(2026, 3, 6),
        limit_up_count=50,
        limit_down_count=10,
        broken_count=5,
        up_down_ratio=5.0,
        broken_rate=broken_rate,
        max_consecutive_height=5,
        avg_consecutive_height=3.0,
        promotion_rate=0.5,
        money_effect_score=score,
        overall_score=score,
        risk_level="LOW",
        description="test",
    )


def _make_candidate(score: float = 70.0, seal_quality: float = 70.0) -> ScoredCandidate:
    return ScoredCandidate(
        ts_code="000001.SZ",
        name="Test",
        score=score,
        factors={"seal_quality": seal_quality, "sentiment": 70},
        signal_type="FIRST_BOARD",
    )


def test_no_go_low_sentiment():
    assessor = RiskAssessor()
    sentiment = _make_sentiment(30)
    candidate = _make_candidate()
    assert assessor.assess(candidate, sentiment) == RiskLevel.NO_GO


def test_no_go_high_broken_rate():
    assessor = RiskAssessor()
    sentiment = _make_sentiment(70, broken_rate=0.55)
    candidate = _make_candidate()
    assert assessor.assess(candidate, sentiment) == RiskLevel.NO_GO


def test_low_risk():
    assessor = RiskAssessor()
    sentiment = _make_sentiment(75)
    candidate = _make_candidate(score=75, seal_quality=80)
    assert assessor.assess(candidate, sentiment) == RiskLevel.LOW


def test_position_hint():
    assert RiskAssessor.position_hint(RiskLevel.LOW) == "FULL"
    assert RiskAssessor.position_hint(RiskLevel.MEDIUM) == "HALF"
    assert RiskAssessor.position_hint(RiskLevel.HIGH) == "QUARTER"
    assert RiskAssessor.position_hint(RiskLevel.NO_GO) == "ZERO"


# ── Helpers for cycle gate tests ──


def _make_cycle(
    phase: CyclePhase,
    score_delta: float = 0.0,
    score_accel: float = 0.0,
) -> SentimentCycle:
    return SentimentCycle(
        phase=phase,
        score_ma3=60.0,
        score_ma5=58.0,
        score_delta=score_delta,
        score_accel=score_accel,
        premium_trend=0.0,
        broken_rate_trend=0.0,
        recent_scores=(60.0, 58.0, 55.0),
        recent_premiums=(0.0,),
        recent_broken_rates=(0.1, 0.12, 0.11),
        is_turning_point=False,
        phase_description="test",
    )


def _make_candidate_with_type(
    score: float = 70.0,
    signal_type: str = "FIRST_BOARD",
) -> ScoredCandidate:
    return ScoredCandidate(
        ts_code="000001.SZ",
        name="Test",
        score=score,
        factors={"seal_quality": 70, "sentiment": 70},
        signal_type=signal_type,
    )


# ── CLIMAX late-phase gate tests ──


def test_climax_late_delta_low_score_first_board_no_go():
    """CLIMAX with negative delta, score below 70 → NO_GO."""
    cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=-2, score_accel=-2.5)
    candidate = _make_candidate_with_type(score=62, signal_type="FIRST_BOARD")
    assert _cycle_gate(candidate, cycle) == RiskLevel.NO_GO


def test_climax_late_accel_sector_leader_high_score_allowed():
    """CLIMAX with accel<-3, SECTOR_LEADER 75+ → HIGH (allowed)."""
    cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=-2, score_accel=-3.5)
    candidate = _make_candidate_with_type(score=78, signal_type="SECTOR_LEADER")
    assert _cycle_gate(candidate, cycle) == RiskLevel.HIGH


def test_climax_early_phase_low():
    """Early CLIMAX (positive delta, positive accel) → LOW."""
    cycle = _make_cycle(CyclePhase.CLIMAX, score_delta=2, score_accel=1)
    candidate = _make_candidate_with_type(score=60, signal_type="FIRST_BOARD")
    assert _cycle_gate(candidate, cycle) == RiskLevel.LOW

"""Tests for risk assessor."""

from datetime import date

from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.signal import RiskLevel
from hit_astocker.signals.composite_scorer import ScoredCandidate
from hit_astocker.signals.risk_assessor import RiskAssessor


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

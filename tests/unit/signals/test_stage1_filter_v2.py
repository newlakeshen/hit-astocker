# tests/unit/signals/test_stage1_filter_v2.py
"""Tests for Stage1 filter thresholds (v2 relaxed thresholds).

Stage1Filter._should_filter() is a @staticmethod that takes (ScoredCandidate, DailyAnalysisContext).
We use MagicMock for both to test individual filter conditions.
"""
from unittest.mock import MagicMock
from hit_astocker.signals.stage1_filter import Stage1Filter, _profit_effect_gate


def _make_candidate(
    signal_type="FIRST_BOARD",
    score=70.0,
    seal_quality=50.0,
    survival=25.0,
    height_momentum=60.0,
    name="平安银行",
    ts_code="000001.SZ",
):
    c = MagicMock()
    c.signal_type = signal_type
    c.score = score
    c.name = name
    c.ts_code = ts_code
    c.factors = {
        "seal_quality": seal_quality,
        "survival": survival,
        "height_momentum": height_momentum,
    }
    return c


def _make_ctx(cycle_phase=None, profit_effect=None):
    ctx = MagicMock()
    ctx.sentiment_cycle = None
    ctx.profit_effect = profit_effect
    if cycle_phase:
        ctx.sentiment_cycle = MagicMock()
        ctx.sentiment_cycle.phase.value = cycle_phase
    return ctx


def test_seal_quality_below_35_filtered():
    """seal_quality=30 should be filtered (<35 threshold)."""
    c = _make_candidate(signal_type="FIRST_BOARD", seal_quality=30.0)
    ctx = _make_ctx()
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is not None
    assert "封板质量" in reason


def test_seal_quality_35_passes():
    """seal_quality=35 passes the threshold."""
    c = _make_candidate(signal_type="FIRST_BOARD", seal_quality=35.0)
    ctx = _make_ctx()
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is None or "封板质量" not in reason


def test_survival_baseline_30():
    """FOLLOW_BOARD with survival=25 filtered (<30 baseline)."""
    c = _make_candidate(signal_type="FOLLOW_BOARD", survival=25.0)
    ctx = _make_ctx()
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is not None
    assert "晋级率" in reason


def test_height3_survival_25():
    """3-board (height_momentum~65 → height=3) with survival=20 filtered (<25)."""
    c = _make_candidate(signal_type="FOLLOW_BOARD", survival=20.0, height_momentum=65.0)
    ctx = _make_ctx()
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is not None
    assert "晋级率" in reason


def test_height3_survival_25_passes():
    """3-board with survival=30 passes (>=25)."""
    c = _make_candidate(signal_type="FOLLOW_BOARD", survival=30.0, height_momentum=65.0)
    ctx = _make_ctx()
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is None or "晋级率不足" not in reason


def test_first_board_profit_effect_tightened():
    """首板赚钱效应: premium < -2.0 and win_rate < 0.35 → filter."""
    pe = MagicMock()
    tier = MagicMock()
    tier.prev_count = 10
    tier.avg_premium = -2.5  # < -2.0
    tier.win_rate = 0.30     # < 0.35
    pe.tier_for_height.return_value = tier
    pe.tier_for_height_by_type.return_value = None  # fallback to tier_for_height
    c = _make_candidate(signal_type="FIRST_BOARD", score=75.0)
    reason = _profit_effect_gate(c, pe)
    assert reason is not None
    assert "首板赚钱效应" in reason


def test_leader_broken_rate_filter():
    """SECTOR_LEADER: 空间板 broken_rate > 60% → filter."""
    pe = MagicMock()
    tier = MagicMock()
    tier.prev_count = 5
    tier.broken_rate = 0.65  # > 60%
    pe.tier_for_height.return_value = tier
    pe.tier_for_height_by_type.return_value = None
    c = _make_candidate(signal_type="SECTOR_LEADER", score=75.0, height_momentum=20.0)
    reason = _profit_effect_gate(c, pe)
    assert reason is not None
    assert "炸板率" in reason

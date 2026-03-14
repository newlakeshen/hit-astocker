# tests/unit/signals/test_stage1_filter.py
"""Tests for FOLLOW_BOARD profit-effect aware survival tightening (Phase 4, Task 2).

Stage1Filter._should_filter() is a @staticmethod that takes (ScoredCandidate, DailyAnalysisContext).
We use MagicMock for both to test the new profit-effect survival gate.
"""
from unittest.mock import MagicMock

from hit_astocker.models.profit_effect import ProfitRegime
from hit_astocker.signals.stage1_filter import Stage1Filter


def _make_candidate(
    signal_type="FOLLOW_BOARD",
    score=70.0,
    seal_quality=50.0,
    survival=40.0,
    height_momentum=65.0,
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


def _make_ctx(profit_regime=None, cycle_phase=None):
    ctx = MagicMock()
    ctx.sentiment_cycle = None
    if cycle_phase:
        ctx.sentiment_cycle = MagicMock()
        ctx.sentiment_cycle.phase.value = cycle_phase

    if profit_regime is not None:
        pe = MagicMock()
        pe.regime = profit_regime
        pe.regime_score = 40.0
        # Avoid _profit_effect_gate tier checks triggering
        pe.tier_for_height.return_value = None
        pe.tier_for_height_by_type.return_value = None
        ctx.profit_effect = pe
    else:
        ctx.profit_effect = None
    return ctx


# ── FOLLOW_BOARD profit-effect survival tightening ──


def test_follow_board_height3_weak_low_survival_filtered():
    """3板 + WEAK regime + survival=30 (<35) → should be filtered."""
    c = _make_candidate(
        signal_type="FOLLOW_BOARD",
        survival=30.0,
        height_momentum=65.0,  # → height=3
        score=70.0,
    )
    ctx = _make_ctx(profit_regime=ProfitRegime.WEAK)
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is not None
    assert "弱赚钱效应连板门槛" in reason
    assert "survival=30<35" in reason


def test_follow_board_height3_weak_sufficient_survival_passes():
    """3板 + WEAK regime + survival=40 (>=35) → should pass."""
    c = _make_candidate(
        signal_type="FOLLOW_BOARD",
        survival=40.0,
        height_momentum=65.0,  # → height=3
        score=70.0,
    )
    ctx = _make_ctx(profit_regime=ProfitRegime.WEAK)
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is None


def test_follow_board_height4_weak_needs_45_filtered():
    """4板 + WEAK regime + survival=40 (<45) → should be filtered."""
    c = _make_candidate(
        signal_type="FOLLOW_BOARD",
        survival=40.0,
        height_momentum=45.0,  # → height=4
        score=70.0,
    )
    ctx = _make_ctx(profit_regime=ProfitRegime.WEAK)
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is not None
    assert "弱赚钱效应连板门槛" in reason
    assert "survival=40<45" in reason


def test_follow_board_height3_strong_regime_no_tightening():
    """3板 + STRONG regime + survival=38 → should pass (no tightening in strong regime)."""
    c = _make_candidate(
        signal_type="FOLLOW_BOARD",
        survival=38.0,
        height_momentum=65.0,  # → height=3
        score=70.0,
    )
    ctx = _make_ctx(profit_regime=ProfitRegime.STRONG)
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is None


def test_follow_board_height3_frozen_regime_filtered():
    """3板 + FROZEN regime + survival=30 (<35) → should be filtered."""
    c = _make_candidate(
        signal_type="FOLLOW_BOARD",
        survival=30.0,
        height_momentum=65.0,  # → height=3
        score=70.0,
    )
    ctx = _make_ctx(profit_regime=ProfitRegime.FROZEN)
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is not None
    assert "弱赚钱效应连板门槛" in reason
    assert "FROZEN" in reason


def test_follow_board_no_profit_effect_no_tightening():
    """3板 + no profit_effect data + survival=38 → should pass (no PE data to gate)."""
    c = _make_candidate(
        signal_type="FOLLOW_BOARD",
        survival=38.0,
        height_momentum=65.0,  # → height=3
        score=70.0,
    )
    ctx = _make_ctx(profit_regime=None)
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is None


def test_follow_board_normal_regime_no_tightening():
    """3板 + NORMAL regime + survival=38 → should pass (NORMAL not tightened)."""
    c = _make_candidate(
        signal_type="FOLLOW_BOARD",
        survival=38.0,
        height_momentum=65.0,  # → height=3
        score=70.0,
    )
    ctx = _make_ctx(profit_regime=ProfitRegime.NORMAL)
    reason = Stage1Filter._should_filter(c, ctx)
    assert reason is None


# ── STRONG_BEAR + WEAK combined market kill ──


def _make_kill_ctx(
    market_regime: str | None = None,
    sh_pct_chg: float = 0.5,
    gem_pct_chg: float = 0.3,
    overall_score: float = 55.0,
    profit_regime: ProfitRegime | None = None,
):
    """Build a minimal DailyAnalysisContext mock for _market_kill tests."""
    ctx = MagicMock()
    if market_regime is not None:
        mc = MagicMock()
        mc.sh_pct_chg = sh_pct_chg
        mc.gem_pct_chg = gem_pct_chg
        mc.market_regime = market_regime
        ctx.sentiment.market_context = mc
    else:
        ctx.sentiment.market_context = None
    ctx.sentiment.overall_score = overall_score
    if profit_regime is not None:
        pe = MagicMock()
        pe.regime = profit_regime
        ctx.profit_effect = pe
    else:
        ctx.profit_effect = None
    return ctx


def test_strong_bear_weak_low_score_kills():
    """STRONG_BEAR + WEAK + score=35 → market_kill returns True."""
    ctx = _make_kill_ctx(
        market_regime="STRONG_BEAR",
        overall_score=35.0,
        profit_regime=ProfitRegime.WEAK,
    )
    assert Stage1Filter._market_kill(ctx) is True


def test_strong_bear_weak_score_above_40_no_kill():
    """STRONG_BEAR + WEAK + score=45 → market_kill returns False (score above 40)."""
    ctx = _make_kill_ctx(
        market_regime="STRONG_BEAR",
        overall_score=45.0,
        profit_regime=ProfitRegime.WEAK,
    )
    assert Stage1Filter._market_kill(ctx) is False


def test_bear_weak_low_score_no_kill():
    """BEAR (not STRONG_BEAR) + WEAK + score=35 → market_kill returns False."""
    ctx = _make_kill_ctx(
        market_regime="BEAR",
        overall_score=35.0,
        profit_regime=ProfitRegime.WEAK,
    )
    assert Stage1Filter._market_kill(ctx) is False

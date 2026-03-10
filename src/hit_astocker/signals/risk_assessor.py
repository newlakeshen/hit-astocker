"""Risk assessment engine — cycle-aware gating.

Classifies candidates into risk levels and determines position sizing.
Supports:
  - Dynamic threshold adjustment based on market regime (大盘联动)
  - Emotion-cycle gating: same score + different direction = different risk
  - Signal-type filtering by cycle phase (e.g., no FIRST_BOARD in DIVERGE)
"""

from hit_astocker.models.index_data import MarketContext
from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.sentiment_cycle import CyclePhase, SentimentCycle
from hit_astocker.models.signal import RiskLevel
from hit_astocker.signals.composite_scorer import ScoredCandidate


class RiskAssessor:
    def assess(
        self,
        candidate: ScoredCandidate,
        sentiment: SentimentScore,
        cycle: SentimentCycle | None = None,
    ) -> RiskLevel:
        """Assess risk level for a candidate. Returns highest applicable risk."""
        ctx = sentiment.market_context
        thresholds = _dynamic_thresholds(ctx)

        # ── Cycle-based gating (hard override) ──
        cycle_risk = _cycle_gate(candidate, cycle)
        if cycle_risk == RiskLevel.NO_GO:
            return RiskLevel.NO_GO

        # Kill conditions -> NO_GO
        if sentiment.overall_score < thresholds["no_go_sentiment"]:
            return RiskLevel.NO_GO
        if sentiment.broken_rate > thresholds["no_go_broken_rate"]:
            return RiskLevel.NO_GO

        # Index-based kill: 大盘暴跌
        if ctx and (ctx.sh_pct_chg <= -3.0 or ctx.gem_pct_chg <= -4.0):
            return RiskLevel.NO_GO

        # High risk conditions
        if sentiment.overall_score < thresholds["high_sentiment"]:
            return max_risk(RiskLevel.HIGH, cycle_risk)

        # Signal-type-specific quality check
        sig_type = candidate.signal_type
        if sig_type == "FIRST_BOARD":
            if candidate.factors.get("seal_quality", 0) < 40:
                return max_risk(RiskLevel.HIGH, cycle_risk)
        elif sig_type == "FOLLOW_BOARD":
            if candidate.factors.get("survival", 0) < 30:
                return max_risk(RiskLevel.HIGH, cycle_risk)
            if candidate.factors.get("height_momentum", 0) < 35:
                return max_risk(RiskLevel.HIGH, cycle_risk)
        elif sig_type == "SECTOR_LEADER":
            if candidate.factors.get("theme_heat", 0) < 40:
                return max_risk(RiskLevel.HIGH, cycle_risk)

        # Index-based high risk: 大盘下跌 + 弱势MA
        if ctx and ctx.sh_pct_chg < -1.0 and ctx.sh_ma20_ratio < 0.99:
            return max_risk(RiskLevel.HIGH, cycle_risk)

        # Medium risk
        if sentiment.overall_score < thresholds["medium_sentiment"]:
            return max_risk(RiskLevel.MEDIUM, cycle_risk)
        if candidate.score < thresholds["medium_score"]:
            return max_risk(RiskLevel.MEDIUM, cycle_risk)

        # Cycle may still elevate risk even when all other checks pass
        if cycle_risk.value in ("HIGH", "MEDIUM"):
            return cycle_risk

        return RiskLevel.LOW

    @staticmethod
    def position_hint(risk: RiskLevel) -> str:
        return {
            RiskLevel.LOW: "FULL",
            RiskLevel.MEDIUM: "HALF",
            RiskLevel.HIGH: "QUARTER",
            RiskLevel.EXTREME: "ZERO",
            RiskLevel.NO_GO: "ZERO",
        }.get(risk, "ZERO")


# ── Cycle gating ─────────────────────────────────────────────────


def _cycle_gate(candidate: ScoredCandidate, cycle: SentimentCycle | None) -> RiskLevel:
    """Apply emotion-cycle phase gating rules.

    Returns the *minimum* risk level imposed by the current cycle phase.
    The caller will take the max of this and the standard risk assessment.

    打板核心逻辑:
      RETREAT → 全面退出, 不参与
      ICE     → 仅允许超高分龙头 (博反包)
      DIVERGE → 首板风险极大, 只允许连板接力
      REPAIR  → 谨慎参与, 提高门槛
      FERMENT → 正常
      CLIMAX  → 正常, 但轻微提高标准 (警惕见顶)
    """
    if cycle is None:
        return RiskLevel.LOW

    phase = cycle.phase
    sig_type = candidate.signal_type
    score = candidate.score

    if phase == CyclePhase.RETREAT:
        # 退潮: 全面空仓, 除非绝对龙头 (>85分且是龙头型)
        if sig_type == "SECTOR_LEADER" and score >= 85:
            return RiskLevel.HIGH
        return RiskLevel.NO_GO

    if phase == CyclePhase.ICE:
        # 冰点: 只博龙头反包, 需极高确信
        if sig_type == "SECTOR_LEADER" and score >= 80:
            return RiskLevel.HIGH
        if sig_type == "FOLLOW_BOARD" and score >= 80:
            return RiskLevel.HIGH
        return RiskLevel.NO_GO

    if phase == CyclePhase.DIVERGE:
        # 分歧: 首板成功率骤降, 只允许已确认趋势的连板
        if sig_type == "FIRST_BOARD":
            return RiskLevel.HIGH if score >= 75 else RiskLevel.NO_GO
        # 连板和龙头正常但提高门槛
        if score < 65:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM

    if phase == CyclePhase.REPAIR:
        # 修复: 提高所有门槛, 轻仓试探
        if score < 60:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM

    if phase == CyclePhase.CLIMAX:
        # 高潮: 正常参与但警惕
        if cycle.score_delta < -3:
            # 高潮末期: score 还高但已开始下滑
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # FERMENT: 正常参与
    return RiskLevel.LOW


# ── Dynamic thresholds ───────────────────────────────────────────


def _dynamic_thresholds(ctx: MarketContext | None) -> dict[str, float]:
    """Compute risk thresholds adjusted by market regime.

    In STRONG_BULL: relax thresholds (allow more aggressive entry)
    In BEAR/STRONG_BEAR: tighten thresholds (more conservative)
    """
    base = {
        "no_go_sentiment": 40.0,
        "no_go_broken_rate": 0.50,
        "high_sentiment": 50.0,
        "medium_sentiment": 65.0,
        "medium_score": 60.0,
    }

    if ctx is None:
        return base

    regime = ctx.market_regime
    if regime == "STRONG_BULL":
        # Relax: lower sentiment threshold, allow more risk
        base["no_go_sentiment"] = 30.0
        base["high_sentiment"] = 40.0
        base["medium_sentiment"] = 55.0
        base["medium_score"] = 50.0
    elif regime == "BULL":
        base["no_go_sentiment"] = 35.0
        base["high_sentiment"] = 45.0
        base["medium_sentiment"] = 60.0
        base["medium_score"] = 55.0
    elif regime == "BEAR":
        # Tighten: require higher scores
        base["no_go_sentiment"] = 45.0
        base["no_go_broken_rate"] = 0.45
        base["high_sentiment"] = 55.0
        base["medium_sentiment"] = 70.0
        base["medium_score"] = 65.0
    elif regime == "STRONG_BEAR":
        base["no_go_sentiment"] = 50.0
        base["no_go_broken_rate"] = 0.40
        base["high_sentiment"] = 60.0
        base["medium_sentiment"] = 75.0
        base["medium_score"] = 70.0

    return base


# ── Helpers ──────────────────────────────────────────────────────


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.EXTREME: 3,
    RiskLevel.NO_GO: 4,
}


def max_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    """Return the higher (more restrictive) of two risk levels."""
    return a if _RISK_ORDER.get(a, 0) >= _RISK_ORDER.get(b, 0) else b

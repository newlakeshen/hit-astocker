"""Risk assessment engine — quality-driven + cycle-aware gating.

Redesigned: risk is primarily driven by individual signal quality (封板质量,
生存率, 题材热度), NOT market sentiment.  Market conditions can elevate risk
but never lower it.

Previous design flaw: sentiment-driven risk was inversely correlated with
actual next-day returns (LOW risk = 31.7% win vs HIGH risk = 48.3% win)
because high-sentiment days = crowded trades = poor returns.

New approach:
  1. Kill conditions (NO_GO): unchanged — market crashes, extreme bearish
  2. Individual quality assessment → base risk level
  3. Cycle gating → can only raise risk
  4. Market sentiment → mild modifier (can raise from LOW→MEDIUM, not more)
"""

from hit_astocker.models.index_data import MarketContext
from hit_astocker.models.profit_effect import ProfitEffectSnapshot, ProfitRegime
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
        profit_effect: ProfitEffectSnapshot | None = None,
    ) -> RiskLevel:
        """Assess risk level for a candidate.

        Priority: kill conditions > cycle gate > quality > market modifier.
        """
        ctx = sentiment.market_context
        thresholds = _dynamic_thresholds(ctx, profit_effect)

        # ── Kill conditions → NO_GO ──
        if sentiment.overall_score < thresholds["no_go_sentiment"]:
            return RiskLevel.NO_GO
        if sentiment.broken_rate > thresholds["no_go_broken_rate"]:
            return RiskLevel.NO_GO
        if ctx and (ctx.sh_pct_chg <= -3.0 or ctx.gem_pct_chg <= -4.0):
            return RiskLevel.NO_GO

        # ── Cycle-based gating (hard override) ──
        cycle_risk = _cycle_gate(candidate, cycle)
        if cycle_risk == RiskLevel.NO_GO:
            return RiskLevel.NO_GO

        # ── Individual quality assessment (core of risk) ──
        quality_risk = _assess_quality(candidate)

        # ── Combine quality + cycle (take more restrictive) ──
        risk = max_risk(quality_risk, cycle_risk)

        # ── Market sentiment modifier (mild, can only raise) ──
        # Very weak sentiment pushes LOW → MEDIUM (not to HIGH)
        if sentiment.overall_score < 45 and risk == RiskLevel.LOW:
            risk = RiskLevel.MEDIUM

        # ── Profit effect overlay ──
        if profit_effect is not None:
            if profit_effect.regime == ProfitRegime.FROZEN:
                risk = max_risk(risk, RiskLevel.HIGH)
            elif profit_effect.regime == ProfitRegime.WEAK and risk == RiskLevel.LOW:
                risk = RiskLevel.MEDIUM

        return risk

    @staticmethod
    def position_hint(risk: RiskLevel) -> str:
        return {
            RiskLevel.LOW: "FULL",
            RiskLevel.MEDIUM: "HALF",
            RiskLevel.HIGH: "QUARTER",
            RiskLevel.EXTREME: "ZERO",
            RiskLevel.NO_GO: "ZERO",
        }.get(risk, "ZERO")


# ── Quality-based risk (new core logic) ──────────────────────────


def _assess_quality(candidate: ScoredCandidate) -> RiskLevel:
    """Assess risk based on individual signal quality.

    Uses composite score + type-specific factors.
    This is the PRIMARY determinant of risk — market conditions are secondary.
    """
    score = candidate.score
    f = candidate.factors
    sig_type = candidate.signal_type

    # ── Score-based baseline ──
    if score >= 70:
        risk = RiskLevel.LOW
    elif score >= 55:
        risk = RiskLevel.MEDIUM
    else:
        risk = RiskLevel.HIGH

    # ── Signal-type-specific quality adjustments ──
    if sig_type == "FIRST_BOARD":
        sq = f.get("seal_quality", 0)
        if sq < 40:
            risk = max_risk(risk, RiskLevel.HIGH)
        elif sq >= 75 and score >= 60:
            # 封板质量优秀 → 可减一级风险
            risk = min_risk(risk, RiskLevel.MEDIUM)

    elif sig_type == "FOLLOW_BOARD":
        surv = f.get("survival", 0)
        hm = f.get("height_momentum", 0)
        if surv < 30 or hm < 20:
            risk = max_risk(risk, RiskLevel.HIGH)
        elif surv >= 60 and hm >= 50:
            risk = min_risk(risk, RiskLevel.MEDIUM)

    elif sig_type == "SECTOR_LEADER":
        th = f.get("theme_heat", 0)
        lp = f.get("leader_position", 0)
        if th < 60 or lp < 60:
            risk = max_risk(risk, RiskLevel.HIGH)
        elif th >= 80 and lp >= 90:
            # 龙一 + 高热度 → 减一级
            risk = min_risk(risk, RiskLevel.MEDIUM)

    return risk


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
        # 分歧: 首板全面禁止, 连板/龙头高门槛
        if sig_type == "FIRST_BOARD":
            return RiskLevel.NO_GO
        if sig_type == "FOLLOW_BOARD":
            return RiskLevel.NO_GO if score < 75 else RiskLevel.HIGH
        if sig_type == "SECTOR_LEADER":
            return RiskLevel.NO_GO if score < 80 else RiskLevel.HIGH
        return RiskLevel.NO_GO if score < 75 else RiskLevel.HIGH

    if phase == CyclePhase.REPAIR:
        # 修复初期 (score_delta > 0): 仅允许高分龙头试探
        if cycle.score_delta > 0:
            if sig_type == "SECTOR_LEADER" and score >= 80:
                return RiskLevel.HIGH
            return RiskLevel.NO_GO
        # 修复后期: 提高门槛, 轻仓试探
        return RiskLevel.HIGH if score < 60 else RiskLevel.MEDIUM

    if phase == CyclePhase.CLIMAX:
        # 高潮末期检测: 一阶导+二阶导协同判断
        # 条件: delta < -1 (情绪已开始下滑) OR accel < -3 (加速恶化)
        is_late_climax = cycle.score_delta < -1 or cycle.score_accel < -3
        if is_late_climax:
            # 高潮末期: 仅 SECTOR_LEADER 75+ 可参与
            if sig_type == "SECTOR_LEADER" and score >= 75:
                return RiskLevel.HIGH
            if score < 70:
                return RiskLevel.NO_GO
            return RiskLevel.HIGH
        return RiskLevel.LOW

    # FERMENT: 正常参与
    return RiskLevel.LOW


# ── Dynamic thresholds ───────────────────────────────────────────


def _dynamic_thresholds(
    ctx: MarketContext | None,
    profit_effect: ProfitEffectSnapshot | None = None,
) -> dict[str, float]:
    """Compute kill-condition thresholds adjusted by market regime.

    Now only controls NO_GO thresholds (kill conditions).
    Individual risk levels are driven by _assess_quality(), not thresholds.
    """
    base = {
        "no_go_sentiment": 40.0,
        "no_go_broken_rate": 0.50,
    }

    if ctx is None:
        return base

    regime = ctx.market_regime
    if regime == "STRONG_BULL":
        base["no_go_sentiment"] = 30.0
    elif regime == "BULL":
        base["no_go_sentiment"] = 35.0
    elif regime == "BEAR":
        base["no_go_sentiment"] = 45.0
        base["no_go_broken_rate"] = 0.45
    elif regime == "STRONG_BEAR":
        base["no_go_sentiment"] = 50.0
        base["no_go_broken_rate"] = 0.40

    # ── Profit effect overlay on kill thresholds ──
    if profit_effect is not None:
        pe_regime = profit_effect.regime
        if pe_regime == ProfitRegime.STRONG:
            base["no_go_sentiment"] -= 3.0
        elif pe_regime == ProfitRegime.WEAK:
            base["no_go_broken_rate"] -= 0.03
        elif pe_regime == ProfitRegime.FROZEN:
            base["no_go_sentiment"] += 5.0
            base["no_go_broken_rate"] -= 0.05

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


def min_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    """Return the lower (less restrictive) of two risk levels."""
    return a if _RISK_ORDER.get(a, 0) <= _RISK_ORDER.get(b, 0) else b

"""Risk assessment engine.

Classifies candidates into risk levels and determines position sizing.
Supports dynamic threshold adjustment based on market context (大盘联动).
"""

from hit_astocker.models.index_data import MarketContext
from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.signal import RiskLevel
from hit_astocker.signals.composite_scorer import ScoredCandidate


class RiskAssessor:
    def assess(self, candidate: ScoredCandidate, sentiment: SentimentScore) -> RiskLevel:
        """Assess risk level for a candidate. Returns highest applicable risk."""
        ctx = sentiment.market_context
        thresholds = _dynamic_thresholds(ctx)

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
            return RiskLevel.HIGH
        if candidate.factors.get("seal_quality", 0) < 40:
            return RiskLevel.HIGH

        # Index-based high risk: 大盘下跌 + 弱势MA
        if ctx and ctx.sh_pct_chg < -1.0 and ctx.sh_ma20_ratio < 0.99:
            return RiskLevel.HIGH

        # Medium risk
        if sentiment.overall_score < thresholds["medium_sentiment"]:
            return RiskLevel.MEDIUM
        if candidate.score < thresholds["medium_score"]:
            return RiskLevel.MEDIUM

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

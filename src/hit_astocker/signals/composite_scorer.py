"""Composite scoring engine.

Aggregates all analyzer outputs into a single score per candidate stock.
Now includes event-driven and stock sentiment factors.
"""

from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.analysis_result import FirstBoardResult, LianbanResult, MoneyFlowResult
from hit_astocker.models.dragon_tiger import DragonTigerResult
from hit_astocker.models.event_data import EventAnalysisResult, StockSentimentScore
from hit_astocker.models.sector import SectorRotationResult
from hit_astocker.models.sentiment import SentimentScore


class ScoredCandidate:
    __slots__ = ("ts_code", "name", "score", "factors", "signal_type")

    def __init__(self, ts_code: str, name: str, score: float, factors: dict[str, float], signal_type: str):
        self.ts_code = ts_code
        self.name = name
        self.score = score
        self.factors = factors
        self.signal_type = signal_type


class CompositeScorer:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()

    def score(
        self,
        sentiment: SentimentScore,
        firstboard_results: list[FirstBoardResult],
        lianban: LianbanResult,
        sector: SectorRotationResult,
        dragon: DragonTigerResult,
        moneyflow_results: list[MoneyFlowResult],
        event_result: EventAnalysisResult | None = None,
        stock_sentiments: list[StockSentimentScore] | None = None,
    ) -> list[ScoredCandidate]:
        s = self._settings
        candidates = []

        # Build lookup maps
        moneyflow_map = {r.ts_code: r for r in moneyflow_results}
        sector_names = {sec.name for sec in sector.top_sectors[:s.signal_top_sector_count]}
        lianban_codes = set()
        for tier in lianban.tiers:
            for code in tier.stocks:
                lianban_codes.add(code)

        # Event & sentiment lookup maps
        event_map = {}
        if event_result:
            event_map = {ev.ts_code: ev for ev in event_result.stock_events}
        sentiment_map = {}
        if stock_sentiments:
            sentiment_map = {ss.ts_code: ss for ss in stock_sentiments}

        # Score first-board candidates
        for fb in firstboard_results:
            factors = {
                "sentiment": sentiment.overall_score,
                "seal_quality": fb.composite_score,
                "sector": 100.0 if fb.industry in sector_names else 30.0,
                "lianban_position": 50.0,  # First board neutral
            }

            # Money flow factor
            mf = moneyflow_map.get(fb.ts_code)
            flow_score = 50.0
            if mf:
                if mf.flow_strength == "STRONG_IN":
                    flow_score = 100.0
                elif mf.flow_strength == "WEAK_IN":
                    flow_score = 70.0

            # Dragon tiger factor
            dt_score = 50.0
            if fb.ts_code in dragon.institutional_net_buy:
                net = dragon.institutional_net_buy[fb.ts_code]
                dt_score = 100.0 if net > 0 else 30.0
            if fb.ts_code in dragon.cooperation_flags:
                dt_score = min(dt_score + 20, 100)

            factors["capital_flow"] = flow_score
            factors["dragon_tiger"] = dt_score

            # Event catalyst factor (事件催化)
            event_score = 50.0
            ev = event_map.get(fb.ts_code)
            if ev:
                event_score = ev.event_weight * 100
            factors["event_catalyst"] = event_score

            # Stock sentiment factor (个股情绪)
            stock_sent_score = 50.0
            ss = sentiment_map.get(fb.ts_code)
            if ss:
                stock_sent_score = ss.composite_score
            factors["stock_sentiment"] = stock_sent_score

            # Weighted composite (adjusted weights to include new factors)
            # Original 6 factors: 25% + 20% + 20% + 15% + 10% + 10% = 100%
            # New 8 factors: reduce existing weights proportionally, add event + sentiment
            composite = (
                0.20 * factors["sentiment"]
                + 0.18 * factors["seal_quality"]
                + 0.15 * factors["sector"]
                + 0.10 * factors["lianban_position"]
                + 0.08 * factors["capital_flow"]
                + 0.08 * factors["dragon_tiger"]
                + 0.11 * factors["event_catalyst"]
                + 0.10 * factors["stock_sentiment"]
            )

            candidates.append(ScoredCandidate(
                ts_code=fb.ts_code,
                name=fb.name,
                score=round(composite, 2),
                factors=factors,
                signal_type="FIRST_BOARD",
            ))

        return sorted(candidates, key=lambda c: c.score, reverse=True)

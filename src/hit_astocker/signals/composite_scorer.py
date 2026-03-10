"""Composite scoring engine (10-factor).

All weights are read from Settings — never hard-coded here.
"""

from hit_astocker.analyzers.board_survival import SurvivalModel
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
        survival_model: SurvivalModel | None = None,
        hsgt_net_map: dict[str, float] | None = None,
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

        # Northbound map
        northbound_map = hsgt_net_map or {}

        # Score first-board candidates
        for fb in firstboard_results:
            factors: dict[str, float] = {
                "sentiment": sentiment.overall_score,
                "seal_quality": fb.composite_score,
                "sector": 100.0 if fb.industry in sector_names else 30.0,
            }

            # Lianban survival factor
            if survival_model and survival_model.stats:
                from hit_astocker.analyzers.board_survival import BoardSurvivalAnalyzer
                factors["lianban_survival"] = BoardSurvivalAnalyzer(None).score_position(
                    1, survival_model,
                )
            else:
                factors["lianban_survival"] = 50.0

            # Money flow factor
            mf = moneyflow_map.get(fb.ts_code)
            flow_score = 50.0
            if mf:
                if mf.flow_strength == "STRONG_IN":
                    flow_score = 100.0
                elif mf.flow_strength == "WEAK_IN":
                    flow_score = 70.0
            factors["capital_flow"] = flow_score

            # Dragon tiger factor
            dt_score = 50.0
            if fb.ts_code in dragon.institutional_net_buy:
                net = dragon.institutional_net_buy[fb.ts_code]
                dt_score = 100.0 if net > 0 else 30.0
            if fb.ts_code in dragon.cooperation_flags:
                dt_score = min(dt_score + 20, 100)
            factors["dragon_tiger"] = dt_score

            # Event catalyst factor
            event_score = 50.0
            ev = event_map.get(fb.ts_code)
            if ev:
                event_score = ev.event_weight * 100
            factors["event_catalyst"] = event_score

            # Stock sentiment factor (8-factor enhanced)
            stock_sent_score = 50.0
            ss = sentiment_map.get(fb.ts_code)
            if ss:
                stock_sent_score = ss.composite_score
            factors["stock_sentiment"] = stock_sent_score

            # Northbound capital factor
            nb_score = 45.0
            nb_net = northbound_map.get(fb.ts_code)
            if nb_net is not None:
                if nb_net >= 10000:
                    nb_score = 100.0
                elif nb_net >= 5000:
                    nb_score = 85.0
                elif nb_net > 0:
                    nb_score = 70.0
                else:
                    nb_score = 25.0
            factors["northbound"] = nb_score

            # Technical form factor
            factors["technical_form"] = ss.technical_form_score if ss else 50.0

            # Weighted composite — all weights from Settings
            composite = (
                s.composite_sentiment_weight * factors["sentiment"]
                + s.composite_seal_quality_weight * factors["seal_quality"]
                + s.composite_sector_weight * factors["sector"]
                + s.composite_lianban_survival_weight * factors["lianban_survival"]
                + s.composite_capital_flow_weight * factors["capital_flow"]
                + s.composite_dragon_tiger_weight * factors["dragon_tiger"]
                + s.composite_event_catalyst_weight * factors["event_catalyst"]
                + s.composite_stock_sentiment_weight * factors["stock_sentiment"]
                + s.composite_northbound_weight * factors["northbound"]
                + s.composite_technical_form_weight * factors["technical_form"]
            )

            candidates.append(ScoredCandidate(
                ts_code=fb.ts_code,
                name=fb.name,
                score=round(composite, 2),
                factors=factors,
                signal_type="FIRST_BOARD",
            ))

        return sorted(candidates, key=lambda c: c.score, reverse=True)

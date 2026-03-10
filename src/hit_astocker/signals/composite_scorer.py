"""Composite scoring engine (10-factor).

Produces three signal types:
  - FIRST_BOARD  — 首板打板 (height=1, first-time limit-up)
  - FOLLOW_BOARD — 连板跟进 (height>=2, consecutive board)
  - SECTOR_LEADER — 板块龙头 (leader of a hot theme, not already scored)

All weights are read from Settings — never hard-coded here.
"""

from hit_astocker.analyzers.board_survival import BoardSurvivalAnalyzer, SurvivalModel
from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.analysis_result import FirstBoardResult, LianbanResult, MoneyFlowResult
from hit_astocker.models.dragon_tiger import DragonTigerResult
from hit_astocker.models.event_data import EventAnalysisResult, StockSentimentScore, ThemeHeat
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

        # ── shared lookup maps ──────────────────────────────────────────
        moneyflow_map = {r.ts_code: r for r in moneyflow_results}
        sector_names = {sec.name for sec in sector.top_sectors[:s.signal_top_sector_count]}

        event_map: dict[str, object] = {}
        if event_result:
            event_map = {ev.ts_code: ev for ev in event_result.stock_events}
        sentiment_map: dict[str, StockSentimentScore] = {}
        if stock_sentiments:
            sentiment_map = {ss.ts_code: ss for ss in stock_sentiments}
        northbound_map = hsgt_net_map or {}

        # ── 1. FIRST_BOARD candidates (首板打板) ────────────────────────
        scored_codes: set[str] = set()
        candidates: list[ScoredCandidate] = []

        for fb in firstboard_results:
            ss = sentiment_map.get(fb.ts_code)
            factors = self._base_factors(
                fb.ts_code, sentiment, sector_names, moneyflow_map,
                dragon, event_map, sentiment_map, northbound_map,
            )
            factors["seal_quality"] = fb.composite_score
            factors["sector"] = 100.0 if fb.industry in sector_names else factors["sector"]

            # Survival: height=1 → P(2|1)
            if survival_model and survival_model.stats:
                factors["lianban_survival"] = BoardSurvivalAnalyzer(None).score_position(
                    1, survival_model,
                )
            else:
                factors["lianban_survival"] = 50.0

            composite = self._weighted_sum(factors, s)
            candidates.append(ScoredCandidate(
                fb.ts_code, fb.name, round(composite, 2), factors, "FIRST_BOARD",
            ))
            scored_codes.add(fb.ts_code)

        # ── 2. FOLLOW_BOARD candidates (连板跟进) ───────────────────────
        for tier in lianban.tiers:
            if tier.height < 2:
                continue
            for code, name in zip(tier.stocks, tier.stock_names, strict=False):
                if code in scored_codes:
                    continue
                ss = sentiment_map.get(code)
                factors = self._base_factors(
                    code, sentiment, sector_names, moneyflow_map,
                    dragon, event_map, sentiment_map, northbound_map,
                )
                # Seal quality unknown for follow boards → neutral
                factors["seal_quality"] = 50.0

                # Survival: use actual height → P(height+1|height)
                if survival_model and survival_model.stats:
                    factors["lianban_survival"] = BoardSurvivalAnalyzer(None).score_position(
                        tier.height, survival_model,
                    )
                else:
                    factors["lianban_survival"] = 50.0

                composite = self._weighted_sum(factors, s)
                candidates.append(ScoredCandidate(
                    code, name, round(composite, 2), factors, "FOLLOW_BOARD",
                ))
                scored_codes.add(code)

        # ── 3. SECTOR_LEADER candidates (板块龙头) ──────────────────────
        if event_result:
            for th in event_result.theme_heats:
                if th.heat_score < 50.0:
                    continue
                for code, name in zip(th.leader_codes, th.leader_names, strict=False):
                    if code in scored_codes:
                        continue
                    factors = self._base_factors(
                        code, sentiment, sector_names, moneyflow_map,
                        dragon, event_map, sentiment_map, northbound_map,
                    )
                    # Leaders of hot themes → full sector score
                    factors["sector"] = 100.0
                    # Seal quality unknown → neutral
                    factors["seal_quality"] = 50.0
                    # Boost event_catalyst with theme heat
                    factors["event_catalyst"] = max(
                        factors["event_catalyst"], th.heat_score,
                    )
                    # Survival: height=1 default (not on lianban ladder)
                    if survival_model and survival_model.stats:
                        factors["lianban_survival"] = BoardSurvivalAnalyzer(None).score_position(
                            1, survival_model,
                        )
                    else:
                        factors["lianban_survival"] = 50.0

                    composite = self._weighted_sum(factors, s)
                    candidates.append(ScoredCandidate(
                        code, name, round(composite, 2), factors, "SECTOR_LEADER",
                    ))
                    scored_codes.add(code)

        return sorted(candidates, key=lambda c: c.score, reverse=True)

    # ── helpers ──────────────────────────────────────────────────────────

    def _base_factors(
        self,
        ts_code: str,
        sentiment: SentimentScore,
        sector_names: set[str],
        moneyflow_map: dict[str, MoneyFlowResult],
        dragon: DragonTigerResult,
        event_map: dict,
        sentiment_map: dict[str, StockSentimentScore],
        northbound_map: dict[str, float],
    ) -> dict[str, float]:
        """Compute the factors that are common across all signal types."""
        factors: dict[str, float] = {
            "sentiment": sentiment.overall_score,
            "seal_quality": 50.0,
            "sector": 30.0,
        }

        # Money flow
        mf = moneyflow_map.get(ts_code)
        if mf:
            if mf.flow_strength == "STRONG_IN":
                factors["capital_flow"] = 100.0
            elif mf.flow_strength == "WEAK_IN":
                factors["capital_flow"] = 70.0
            else:
                factors["capital_flow"] = 50.0
        else:
            factors["capital_flow"] = 50.0

        # Dragon tiger
        dt_score = 50.0
        if ts_code in dragon.institutional_net_buy:
            net = dragon.institutional_net_buy[ts_code]
            dt_score = 100.0 if net > 0 else 30.0
        if ts_code in dragon.cooperation_flags:
            dt_score = min(dt_score + 20, 100)
        factors["dragon_tiger"] = dt_score

        # Event catalyst
        ev = event_map.get(ts_code)
        factors["event_catalyst"] = ev.event_weight * 100 if ev else 50.0

        # Stock sentiment (8-factor)
        ss = sentiment_map.get(ts_code)
        factors["stock_sentiment"] = ss.composite_score if ss else 50.0

        # Northbound
        nb_net = northbound_map.get(ts_code)
        if nb_net is not None:
            if nb_net >= 10000:
                factors["northbound"] = 100.0
            elif nb_net >= 5000:
                factors["northbound"] = 85.0
            elif nb_net > 0:
                factors["northbound"] = 70.0
            else:
                factors["northbound"] = 25.0
        else:
            factors["northbound"] = 45.0

        # Technical form
        factors["technical_form"] = ss.technical_form_score if ss else 50.0

        # Lianban survival — placeholder, overridden by caller
        factors["lianban_survival"] = 50.0

        return factors

    @staticmethod
    def _weighted_sum(factors: dict[str, float], s: Settings) -> float:
        return (
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

"""Composite scoring engine — three independent models.

Each signal type has its own factor set, weight distribution, and scoring logic:
  - FIRST_BOARD  (首板弱转强/回封): seal_quality 为核心
  - FOLLOW_BOARD (2-3板接力):       survival + height_momentum 为核心
  - SECTOR_LEADER(空间板龙头):      theme_heat + leader_position 为核心

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

        shared = _SharedMaps(
            sentiment=sentiment,
            sector_names=sector_names,
            moneyflow_map=moneyflow_map,
            dragon=dragon,
            event_map=event_map,
            sentiment_map=sentiment_map,
            northbound_map=northbound_map,
            survival_model=survival_model,
        )

        # ── 1. FIRST_BOARD (首板弱转强/回封) ─────────────────────────
        scored_codes: set[str] = set()
        candidates: list[ScoredCandidate] = []

        for fb in firstboard_results:
            factors = _common_factors(fb.ts_code, shared)
            factors["seal_quality"] = fb.composite_score
            factors["sector"] = 100.0 if fb.industry in sector_names else factors["sector"]
            factors["survival"] = _survival_score(1, survival_model)

            weights = _fb_weights(s)
            composite = _weighted_sum(factors, weights)
            candidates.append(ScoredCandidate(
                fb.ts_code, fb.name, round(composite, 2), factors, "FIRST_BOARD",
            ))
            scored_codes.add(fb.ts_code)

        # ── 2. FOLLOW_BOARD (2-3板接力) ──────────────────────────────
        for tier in lianban.tiers:
            if tier.height < 2:
                continue
            for code, name in zip(tier.stocks, tier.stock_names, strict=False):
                if code in scored_codes:
                    continue
                factors = _common_factors(code, shared)
                factors["survival"] = _survival_score(tier.height, survival_model)
                factors["height_momentum"] = _score_height_momentum(tier.height)

                weights = _fl_weights(s)
                composite = _weighted_sum(factors, weights)
                candidates.append(ScoredCandidate(
                    code, name, round(composite, 2), factors, "FOLLOW_BOARD",
                ))
                scored_codes.add(code)

        # ── 3. SECTOR_LEADER (空间板龙头) ────────────────────────────
        if event_result:
            for th in event_result.theme_heats:
                if th.heat_score < 50.0:
                    continue
                for code, name in zip(th.leader_codes, th.leader_names, strict=False):
                    if code in scored_codes:
                        continue
                    factors = _common_factors(code, shared)
                    factors["theme_heat"] = th.heat_score
                    factors["leader_position"] = _score_leader_position(code, th)
                    # Leaders of hot themes → full sector score
                    factors["sector"] = 100.0
                    # Boost event_catalyst with theme heat
                    factors["event_catalyst"] = max(
                        factors["event_catalyst"], th.heat_score,
                    )

                    weights = _sl_weights(s)
                    composite = _weighted_sum(factors, weights)
                    candidates.append(ScoredCandidate(
                        code, name, round(composite, 2), factors, "SECTOR_LEADER",
                    ))
                    scored_codes.add(code)

        return sorted(candidates, key=lambda c: c.score, reverse=True)


# ── shared data container ─────────────────────────────────────────────


class _SharedMaps:
    """Lightweight holder to reduce parameter passing."""
    __slots__ = (
        "sentiment", "sector_names", "moneyflow_map", "dragon",
        "event_map", "sentiment_map", "northbound_map", "survival_model",
    )

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ── common factor computation ─────────────────────────────────────────


def _common_factors(ts_code: str, m: _SharedMaps) -> dict[str, float]:
    """Compute factors shared by all three signal types."""
    factors: dict[str, float] = {
        "sentiment": m.sentiment.overall_score,
        "sector": 30.0,
    }

    # Money flow
    mf = m.moneyflow_map.get(ts_code)
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
    if ts_code in m.dragon.institutional_net_buy:
        net = m.dragon.institutional_net_buy[ts_code]
        dt_score = 100.0 if net > 0 else 30.0
    if ts_code in m.dragon.cooperation_flags:
        dt_score = min(dt_score + 20, 100)
    factors["dragon_tiger"] = dt_score

    # Event catalyst
    ev = m.event_map.get(ts_code)
    factors["event_catalyst"] = ev.event_weight * 100 if ev else 50.0

    # Stock sentiment (8-factor)
    ss = m.sentiment_map.get(ts_code)
    factors["stock_sentiment"] = ss.composite_score if ss else 50.0

    # Northbound
    nb_net = m.northbound_map.get(ts_code)
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

    return factors


# ── type-specific factor scoring ──────────────────────────────────────


def _survival_score(height: int, model: SurvivalModel | None) -> float:
    """P(height+1 | height) → 0-100 score."""
    if model and model.stats:
        return BoardSurvivalAnalyzer(None).score_position(height, model)
    return 50.0


def _score_height_momentum(height: int) -> float:
    """2-3板最优接力位, 4板以上风险递增.

    打板实战经验:
      2板 → 最佳接力 (分歧转一致, 辨识度刚建立)
      3板 → 趋势确认 (需更强催化)
      4板 → 进入高位区 (需极强主线地位)
      5板+ → 只有绝对龙头才敢接 (博弈空间板)
    """
    if height == 2:
        return 95.0
    if height == 3:
        return 80.0
    if height == 4:
        return 60.0
    if height == 5:
        return 40.0
    return max(20.0, 100 - height * 15)


def _score_leader_position(code: str, theme: ThemeHeat) -> float:
    """板块内龙头地位: 龙一 > 龙二 > 龙三.

    龙一辨识度最高、封单最强、跟风资金最多,
    龙二龙三只有在龙一开板/断板时才有接力价值.
    """
    codes = list(theme.leader_codes)
    if code not in codes:
        return 30.0
    idx = codes.index(code)
    if idx == 0:
        return 100.0
    if idx == 1:
        return 75.0
    if idx == 2:
        return 60.0
    return 45.0


# ── weight builders (read from Settings) ──────────────────────────────


def _fb_weights(s: Settings) -> dict[str, float]:
    """FIRST_BOARD factor → weight mapping."""
    return {
        "sentiment": s.fb_sentiment_weight,
        "seal_quality": s.fb_seal_quality_weight,
        "sector": s.fb_sector_weight,
        "survival": s.fb_survival_weight,
        "capital_flow": s.fb_capital_flow_weight,
        "dragon_tiger": s.fb_dragon_tiger_weight,
        "event_catalyst": s.fb_event_catalyst_weight,
        "stock_sentiment": s.fb_stock_sentiment_weight,
        "northbound": s.fb_northbound_weight,
        "technical_form": s.fb_technical_form_weight,
    }


def _fl_weights(s: Settings) -> dict[str, float]:
    """FOLLOW_BOARD factor → weight mapping."""
    return {
        "sentiment": s.fl_sentiment_weight,
        "survival": s.fl_survival_weight,
        "height_momentum": s.fl_height_momentum_weight,
        "sector": s.fl_sector_weight,
        "capital_flow": s.fl_capital_flow_weight,
        "dragon_tiger": s.fl_dragon_tiger_weight,
        "event_catalyst": s.fl_event_catalyst_weight,
        "stock_sentiment": s.fl_stock_sentiment_weight,
        "northbound": s.fl_northbound_weight,
        "technical_form": s.fl_technical_form_weight,
    }


def _sl_weights(s: Settings) -> dict[str, float]:
    """SECTOR_LEADER factor → weight mapping."""
    return {
        "sentiment": s.sl_sentiment_weight,
        "theme_heat": s.sl_theme_heat_weight,
        "leader_position": s.sl_leader_position_weight,
        "sector": s.sl_sector_weight,
        "capital_flow": s.sl_capital_flow_weight,
        "dragon_tiger": s.sl_dragon_tiger_weight,
        "event_catalyst": s.sl_event_catalyst_weight,
        "stock_sentiment": s.sl_stock_sentiment_weight,
        "northbound": s.sl_northbound_weight,
        "technical_form": s.sl_technical_form_weight,
    }


def _weighted_sum(factors: dict[str, float], weights: dict[str, float]) -> float:
    """Compute weighted sum — only factors present in weights are included."""
    return sum(weights[k] * factors.get(k, 50.0) for k in weights)

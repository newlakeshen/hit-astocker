"""Composite scoring engine — three independent models.

Each signal type has its own factor set, weight distribution, and scoring logic:
  - FIRST_BOARD  (首板弱转强/回封): seal_quality 为核心
  - FOLLOW_BOARD (2-3板接力):       survival + height_momentum 为核心
  - SECTOR_LEADER(空间板龙头):      theme_heat + leader_position 为核心

All weights are read from Settings — never hard-coded here.

Dynamic weight redistribution:
  When a factor's backing data is entirely missing (table empty / not synced),
  the factor is set to None and its weight is redistributed proportionally
  to factors with real data. This prevents phantom 45/50 defaults from
  inflating scores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hit_astocker.analyzers.board_survival import BoardSurvivalAnalyzer, SurvivalModel
from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.analysis_result import FirstBoardResult, LianbanResult, MoneyFlowResult
from hit_astocker.models.dragon_tiger import DragonTigerResult
from hit_astocker.models.event_data import EventAnalysisResult, StockSentimentScore, ThemeHeat
from hit_astocker.models.sector import SectorRotationResult
from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.sentiment_cycle import CyclePhase, SentimentCycle

if TYPE_CHECKING:
    from hit_astocker.models.daily_context import DataCoverage


class ScoredCandidate:
    __slots__ = ("ts_code", "name", "score", "factors", "signal_type", "theme")

    def __init__(
        self,
        ts_code: str,
        name: str,
        score: float,
        factors: dict[str, float],
        signal_type: str,
        theme: str = "",
    ):
        self.ts_code = ts_code
        self.name = name
        self.score = score
        self.factors = factors
        self.signal_type = signal_type
        self.theme = theme


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
        coverage: DataCoverage | None = None,
        cycle: SentimentCycle | None = None,
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
            coverage=coverage,
            cycle=cycle,
        )

        # ── 1. FIRST_BOARD (首板弱转强/回封) ─────────────────────────
        scored_codes: set[str] = set()
        candidates: list[ScoredCandidate] = []

        for fb in firstboard_results:
            raw = _common_factors(fb.ts_code, shared)
            raw["seal_quality"] = fb.composite_score
            raw["sector"] = 100.0 if fb.industry in sector_names else raw["sector"]
            raw["survival"] = _survival_score(1, survival_model)

            weights = _cycle_adjust_weights(_fb_weights(s), cycle, "FIRST_BOARD")
            composite = _weighted_sum(raw, weights)
            clean = {k: v for k, v in raw.items() if v is not None}
            candidates.append(ScoredCandidate(
                fb.ts_code, fb.name, round(composite, 2), clean, "FIRST_BOARD",
                theme=fb.industry,
            ))
            scored_codes.add(fb.ts_code)

        # ── 2. FOLLOW_BOARD (2-3板接力) ──────────────────────────────
        for tier in lianban.tiers:
            if tier.height < 2:
                continue
            for code, name in zip(tier.stocks, tier.stock_names, strict=False):
                if code in scored_codes:
                    continue
                raw = _common_factors(code, shared)
                raw["survival"] = _survival_score(tier.height, survival_model)
                raw["height_momentum"] = _score_height_momentum(tier.height, survival_model)

                weights = _cycle_adjust_weights(_fl_weights(s), cycle, "FOLLOW_BOARD")
                composite = _weighted_sum(raw, weights)
                clean = {k: v for k, v in raw.items() if v is not None}
                # 题材: 从事件分类获取, fallback 为空
                ev = shared.event_map.get(code)
                fl_theme = ev.theme if ev else ""
                candidates.append(ScoredCandidate(
                    code, name, round(composite, 2), clean, "FOLLOW_BOARD",
                    theme=fl_theme,
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
                    raw = _common_factors(code, shared)
                    raw["theme_heat"] = th.heat_score
                    raw["leader_position"] = _score_leader_position(code, th)
                    # Leaders of hot themes → full sector score
                    raw["sector"] = 100.0
                    # Boost event_catalyst with theme heat
                    ec = raw.get("event_catalyst") or 50.0
                    raw["event_catalyst"] = max(ec, th.heat_score)

                    weights = _cycle_adjust_weights(_sl_weights(s), cycle, "SECTOR_LEADER")
                    composite = _weighted_sum(raw, weights)
                    clean = {k: v for k, v in raw.items() if v is not None}
                    candidates.append(ScoredCandidate(
                        code, name, round(composite, 2), clean, "SECTOR_LEADER",
                        theme=th.theme_name,
                    ))
                    scored_codes.add(code)

        return sorted(candidates, key=lambda c: c.score, reverse=True)


# ── shared data container ─────────────────────────────────────────────


class _SharedMaps:
    """Lightweight holder to reduce parameter passing."""
    __slots__ = (
        "sentiment", "sector_names", "moneyflow_map", "dragon",
        "event_map", "sentiment_map", "northbound_map", "survival_model",
        "coverage", "cycle",
    )

    def __init__(
        self,
        sentiment: SentimentScore,
        sector_names: set[str],
        moneyflow_map: dict[str, MoneyFlowResult],
        dragon: DragonTigerResult,
        event_map: dict[str, object],
        sentiment_map: dict[str, StockSentimentScore],
        northbound_map: dict[str, float],
        survival_model: SurvivalModel | None,
        coverage: DataCoverage | None,
        cycle: SentimentCycle | None = None,
    ) -> None:
        self.sentiment = sentiment
        self.sector_names = sector_names
        self.moneyflow_map = moneyflow_map
        self.dragon = dragon
        self.event_map = event_map
        self.sentiment_map = sentiment_map
        self.northbound_map = northbound_map
        self.survival_model = survival_model
        self.coverage = coverage
        self.cycle = cycle


# ── common factor computation ─────────────────────────────────────────


def _common_factors(ts_code: str, m: _SharedMaps) -> dict[str, float | None]:
    """Compute factors shared by all three signal types.

    Returns None for factors whose backing data source is empty.
    _weighted_sum() will skip None factors and renormalize weights.
    """
    cov = m.coverage  # may be None (backward compat)

    factors: dict[str, float | None] = {
        "sentiment": m.sentiment.overall_score,
        "sector": 30.0,
    }

    # Money flow (moneyflow_ths has data)
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

    # Dragon tiger — quantified seat profile (hm_detail) with inst fallback
    # top_list/top_inst always have data; hm boost is optional
    dt_score: float = 45.0
    seat = m.dragon.seat_scores.get(ts_code)
    if seat:
        dt_score = 55.0
        dt_score += seat.max_win_rate * 25
        if seat.is_coordinated:
            dt_score += 12.0
        if seat.known_net_amount > 0:
            dt_score += 5.0
        elif seat.known_net_amount < 0:
            dt_score -= 10.0
        dt_score = max(0, min(dt_score, 100))
    elif ts_code in m.dragon.institutional_net_buy:
        net = m.dragon.institutional_net_buy[ts_code]
        dt_score = 70.0 if net > 0 else 30.0
    factors["dragon_tiger"] = dt_score

    # Event catalyst (KPL L3 fallback always available)
    ev = m.event_map.get(ts_code)
    factors["event_catalyst"] = ev.event_weight * 100 if ev else 50.0

    # Stock sentiment (composite — internally uses dynamic weighting)
    ss = m.sentiment_map.get(ts_code)
    factors["stock_sentiment"] = ss.composite_score if ss else 50.0

    # Northbound — None when hsgt_top10 is empty (no data synced)
    if cov and not cov.has_hsgt:
        factors["northbound"] = None
    else:
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
            factors["northbound"] = 45.0  # not in top 10, but table has data

    # Technical form — None when stk_factor_pro is empty
    if cov and not cov.has_stk_factor:
        factors["technical_form"] = None
    else:
        factors["technical_form"] = ss.technical_form_score if ss else 50.0

    # Auction quality — None when stk_auction is empty
    if cov and not cov.has_auction:
        factors["auction_quality"] = None
    else:
        factors["auction_quality"] = ss.bid_activity_score if ss else 50.0

    return factors


# ── type-specific factor scoring ──────────────────────────────────────


def _survival_score(height: int, model: SurvivalModel | None) -> float:
    """P(height+1 | height) → 0-100 score."""
    if model and model.stats and model.total_samples >= 100:
        return BoardSurvivalAnalyzer(None).score_position(height, model)
    # 样本不足时用经验衰减: 连板越高晋级率越低
    return _fallback_survival_score(height)


def _fallback_survival_score(height: int) -> float:
    """样本不足时的经验生存率评分 (A股打板统计经验值).

    连板可能性随高度递减:
      1板→2板: ~60% 晋级率 → score 75
      2板→3板: ~35% 晋级率 → score 55
      3板→4板: ~25% 晋级率 → score 45
      4板→5板: ~15% 晋级率 → score 35
      5板+:   ~10% 晋级率 → score 30
    """
    fallback_map = {1: 75.0, 2: 55.0, 3: 45.0, 4: 35.0, 5: 30.0}
    if height in fallback_map:
        return fallback_map[height]
    return max(20.0, 35.0 - (height - 4) * 5)


def _score_height_momentum(height: int, model: SurvivalModel | None = None) -> float:
    """连板高度动量评分 — 基于实际生存率的衰减模型.

    核心逻辑: 连板可能性随高度递增而递减.

    当有生存率模型时:
      1. 用实际 P(N+1|N) 单步概率作为基础 (数据驱动)
      2. 计算累积存活概率 P(1→N) = ∏ P(k+1|k), k=1..N-1
      3. 综合分 = 40%单步概率 + 40%累积衰减 + 20%位置奖惩
      - 2板有位置加成(最优接力位), 5板+有额外惩罚(博弈属性)

    无模型时回退到经验阈值.
    """
    # 需要足够样本才能用数据驱动 (至少100个样本, 至少10个交易日)
    if model and model.stats and model.total_samples >= 100:
        return _data_driven_height_momentum(height, model)

    # Fallback: 静态经验值 (连板可能性随高度递减)
    if height == 2:
        return 90.0
    if height == 3:
        return 72.0
    if height == 4:
        return 50.0
    if height == 5:
        return 32.0
    return max(10.0, 80 - height * 15)


def _data_driven_height_momentum(height: int, model: SurvivalModel) -> float:
    """数据驱动的高度动量: 用历史生存率替代硬编码.

    连板的可能性随时间越来越弱:
      - 单步概率 P(N+1|N): 当前高度的晋级概率 (直接衰减)
      - 累积概率 P(1→N): 从首板到当前高度的存活概率 (乘性衰减, 下降更快)
      - 位置调整: 2板是最优接力位(+bonus), 超高板有博弈惩罚
    """
    rate_map = {s.height: s.survival_rate for s in model.stats}

    # ── 1. 单步概率 P(N+1|N) → 0-100 分 ──
    step_rate = rate_map.get(height, 0.15)  # 无数据默认保守值
    # 映射: rate 0.6+ → 95, 0.5 → 80, 0.3 → 50, 0.15 → 25, 0.05 → 10
    step_score = min(100.0, max(5.0, step_rate * 160))

    # ── 2. 累积存活概率 P(1→N) = ∏ P(k+1|k), k=1..N-1 ──
    cumulative = 1.0
    for k in range(1, height):
        rate_k = rate_map.get(k, 0.15)
        cumulative *= rate_k
    # 累积概率 → 分数 (衰减更快, 强调连板越来越难)
    # 映射: 0.5 → 85, 0.3 → 65, 0.15 → 45, 0.05 → 20, 0.01 → 5
    cumul_score = min(100.0, max(5.0, cumulative * 170))

    # ── 3. 位置调整 ──
    # 2板是最优接力位 (分歧转一致, 辨识度刚建立)
    # 5板+进入纯博弈区, 额外惩罚
    position_adj = 0.0
    if height == 2:
        position_adj = 10.0   # 最佳接力位加成
    elif height == 3:
        position_adj = 3.0    # 趋势确认, 微加
    elif height >= 5:
        position_adj = -5.0 * (height - 4)  # 每超1板扣5分

    # ── 综合: 40%单步 + 40%累积 + 20%位置 ──
    raw = 0.40 * step_score + 0.40 * cumul_score + 0.20 * (50.0 + position_adj)
    return round(min(100.0, max(5.0, raw)), 1)


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
        "auction_quality": s.fb_auction_quality_weight,
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
        "auction_quality": s.fl_auction_quality_weight,
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
        "auction_quality": s.sl_auction_quality_weight,
    }


def _cycle_adjust_weights(
    weights: dict[str, float],
    cycle: SentimentCycle | None,
    signal_type: str,
) -> dict[str, float]:
    """Apply cycle-phase-based gating to factor weights.

    打板策略在不同情绪周期下, 各因子的预测力差异巨大:
    - ICE/RETREAT: 技术面完全失效, 只有确定性因子 (封板/龙头/生存率) 有意义
    - CLIMAX: 所有因子正常, 但应增加确定性因子权重 (警惕拐点)
    - DIVERGE: 首板因子大幅降权 (炸板概率高), 生存率权重提升

    调整后自动归一化到 sum=1, 不影响 _weighted_sum 的重分配逻辑.
    """
    if cycle is None:
        return weights

    phase = cycle.phase
    adjusted = dict(weights)

    if phase in (CyclePhase.ICE, CyclePhase.RETREAT):
        # 冰点/退潮: 技术面、资金面失效
        for k in ("technical_form", "capital_flow", "northbound"):
            if k in adjusted:
                adjusted[k] *= 0.3
        # 提升确定性因子 (竞价承接在冰点更关键)
        for k in ("seal_quality", "survival", "leader_position", "theme_heat", "auction_quality"):
            if k in adjusted:
                adjusted[k] *= 1.4
    elif phase == CyclePhase.DIVERGE:
        # 分歧: 减弱偏乐观因子, 增强安全边际因子
        for k in ("event_catalyst", "stock_sentiment"):
            if k in adjusted:
                adjusted[k] *= 0.6
        for k in ("survival", "seal_quality"):
            if k in adjusted:
                adjusted[k] *= 1.3
    elif phase == CyclePhase.REPAIR:
        # 修复: 增加确定性要求
        for k in ("seal_quality", "survival", "leader_position"):
            if k in adjusted:
                adjusted[k] *= 1.2
    elif phase == CyclePhase.CLIMAX:
        # 高潮: 轻微偏向确定性 (防拐点)
        if cycle.score_delta < -3:
            # 高潮末期
            for k in ("seal_quality", "survival"):
                if k in adjusted:
                    adjusted[k] *= 1.2
            for k in ("event_catalyst",):
                if k in adjusted:
                    adjusted[k] *= 0.8

    # Renormalize to sum=1
    total = sum(adjusted.values())
    if total > 0:
        return {k: v / total for k, v in adjusted.items()}
    return weights


def _weighted_sum(factors: dict[str, float | None], weights: dict[str, float]) -> float:
    """Compute weighted sum with dynamic renormalization.

    Factors set to None (no backing data) are skipped entirely.
    Their weight is redistributed proportionally to available factors.
    When all factors have data, this is equivalent to a simple weighted sum.
    """
    available: list[tuple[str, float]] = []
    for k in weights:
        v = factors.get(k)
        if v is not None:
            available.append((k, v))
    if not available:
        return 0.0
    total_w = sum(weights[k] for k, _ in available)
    if total_w <= 0:
        return 0.0
    return sum(weights[k] / total_w * v for k, v in available)

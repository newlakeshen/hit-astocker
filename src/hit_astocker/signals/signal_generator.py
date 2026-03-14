"""Signal generation engine — two-stage pipeline with portfolio constraints.

Stage 1 (Hard filter): Remove non-tradeable samples via rule-based gates.
Stage 2 (Cross-sectional ranking): Score survivors using either:
  - ML model (logistic / GBDT, when trained model exists)
  - Rule-based weighted scoring (fallback)
Stage 3 (Risk assessment): Determine position sizing per signal.
Stage 4 (Portfolio constraints): Dynamic threshold + TopK + concentration limits.

Supports two entry points:
  - generate_from_context(ctx) — preferred, uses pre-computed DailyAnalysisContext
  - generate(trade_date)       — convenience wrapper, builds context internally
"""

import logging
import sqlite3
from datetime import date
from pathlib import Path

from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.daily_context import DailyAnalysisContext, build_daily_context
from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.sentiment_cycle import CyclePhase, SentimentCycle
from hit_astocker.models.signal import RiskLevel, SignalType, TradingSignal
from hit_astocker.signals.composite_scorer import CompositeScorer
from hit_astocker.signals.feature_builder import build_feature_matrix
from hit_astocker.signals.ranking_model import RankingModel
from hit_astocker.signals.risk_assessor import RiskAssessor
from hit_astocker.signals.stage1_filter import Stage1Filter

logger = logging.getLogger(__name__)
_MIN_MODEL_AUC = 0.60


class SignalGenerator:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings | None = None,
        *,
        llm_client=None,
        llm_cache=None,
    ):
        self._conn = conn
        self._settings = settings or get_settings()
        self._scorer = CompositeScorer(self._settings)
        self._risk_assessor = RiskAssessor()
        self._stage1_filter = Stage1Filter()
        self._llm_client = llm_client
        self._llm_cache = llm_cache
        # Try to load ML ranking model (disabled by default, enable via settings)
        self._ranking_model = RankingModel()
        self._use_ml = False
        if self._settings.use_ml_model:
            model_path = Path(self._settings.db_path).parent / "ranking_model.pkl"
            loaded = self._ranking_model.load(model_path)
            self._use_ml = loaded and self._ranking_model.is_usable(_MIN_MODEL_AUC)
            if self._use_ml:
                logger.info("ML ranking model loaded — using two-stage pipeline")
            elif loaded:
                logger.warning(
                    "Ranking model loaded but disabled: AUC below %.2f threshold",
                    _MIN_MODEL_AUC,
                )

    # -- public API ----------------------------------------------------------

    def generate(self, trade_date: date) -> list[TradingSignal]:
        """Build context internally and generate signals (standalone usage)."""
        ctx = build_daily_context(self._conn, self._settings, trade_date)
        return self.generate_from_context(ctx)

    def generate_from_context(self, ctx: DailyAnalysisContext) -> list[TradingSignal]:
        """Generate signals from a pre-computed analysis context.

        Pipeline:
        1. CompositeScorer: extract factor vectors for all candidates
        2. Stage1Filter: remove hard NO_GO samples
        3. Ranking: ML model (if trained) or rule-based weighted sum
        4. RiskAssessor: determine position sizing for each signal
        """
        # ── Step 1: Factor extraction (same as before) ──
        scored = self._scorer.score(
            ctx.sentiment,
            list(ctx.firstboard),
            ctx.lianban,
            ctx.sector,
            ctx.dragon,
            list(ctx.moneyflow),
            event_result=ctx.event,
            stock_sentiments=list(ctx.stock_sentiments),
            survival_model=ctx.survival_model,
            hsgt_net_map=ctx.hsgt_net_map,
            coverage=ctx.coverage,
            cycle=ctx.sentiment_cycle,
        )

        # ── Step 2: Stage 1 hard filter ──
        survivors = self._stage1_filter.filter(scored, ctx)

        if not survivors:
            return []

        # ── Step 3: Cross-sectional ranking ──
        if self._use_ml:
            signals = self._ml_rank(survivors, ctx)
        else:
            signals = self._rule_rank(survivors, ctx)

        signals = sorted(signals, key=lambda s: s.composite_score, reverse=True)

        # ── Step 4: Portfolio constraints (score threshold + TopK + concentration) ──
        signals = self._apply_portfolio_constraints(signals, ctx)

        # ── Optional: LLM-enhanced signal reasons ──
        if self._llm_client is not None and signals:
            signals = self._enhance_reasons_with_llm(signals, ctx)

        return signals

    # -- Stage 2a: ML-based ranking ------------------------------------------

    def _ml_rank(self, candidates, ctx: DailyAnalysisContext) -> list[TradingSignal]:
        """Stage 2 (ML): score candidates using trained model."""
        # Build feature matrix
        features = build_feature_matrix(
            candidates,
            ctx.sentiment_cycle,
            ctx.coverage,
        )

        # Predict probability of profitable trade
        try:
            proba = self._ranking_model.predict_proba(features)
        except Exception:
            logger.warning("ML prediction failed, falling back to rules", exc_info=True)
            return self._rule_rank(candidates, ctx)

        # Convert probabilities to signals
        signals = []
        for candidate, prob in zip(candidates, proba, strict=True):
            # ML score: probability * 100 (0-100 scale)
            ml_score = round(prob * 100, 2)

            # Risk assessment still uses rule-based logic for position sizing
            risk = self._risk_assessor.assess(
                candidate,
                ctx.sentiment,
                cycle=ctx.sentiment_cycle,
                profit_effect=ctx.profit_effect,
            )
            if risk == RiskLevel.NO_GO:
                continue

            position = RiskAssessor.position_hint(risk)
            reason = self._build_reason(candidate, ctx.sentiment, ctx.lianban, ctx.event)

            signals.append(
                TradingSignal(
                    trade_date=ctx.trade_date,
                    ts_code=candidate.ts_code,
                    name=candidate.name,
                    signal_type=SignalType(candidate.signal_type),
                    composite_score=ml_score,
                    risk_level=risk,
                    position_hint=position,
                    factors=candidate.factors,
                    reason=reason,
                    score_source="model",
                    theme=candidate.theme,
                )
            )

        return signals

    # -- Stage 2b: Rule-based ranking (fallback) -----------------------------

    def _rule_rank(self, candidates, ctx: DailyAnalysisContext) -> list[TradingSignal]:
        """Stage 2 (rules): use weighted composite score for ranking."""
        signals = []
        for candidate in candidates:
            risk = self._risk_assessor.assess(
                candidate,
                ctx.sentiment,
                cycle=ctx.sentiment_cycle,
                profit_effect=ctx.profit_effect,
            )
            if risk == RiskLevel.NO_GO:
                continue

            position = RiskAssessor.position_hint(risk)
            reason = self._build_reason(candidate, ctx.sentiment, ctx.lianban, ctx.event)

            signals.append(
                TradingSignal(
                    trade_date=ctx.trade_date,
                    ts_code=candidate.ts_code,
                    name=candidate.name,
                    signal_type=SignalType(candidate.signal_type),
                    composite_score=candidate.score,
                    risk_level=risk,
                    position_hint=position,
                    factors=candidate.factors,
                    reason=reason,
                    score_source="rules",
                    theme=candidate.theme,
                )
            )

        return signals

    # -- Step 4: Portfolio constraints ----------------------------------------

    def _apply_portfolio_constraints(
        self,
        signals: list[TradingSignal],
        ctx: DailyAnalysisContext,
    ) -> list[TradingSignal]:
        """Apply dynamic threshold, concentration limits, and TopK.

        Signals must be pre-sorted by composite_score DESC.
        Processing order:
          1. Dynamic score threshold (市场状态自适应)
          2. Per-theme concentration (单题材最多 N 只, 防抱团)
          3. Per-type concentration (单板型最多 N 只, 防偏科)
          4. TopK daily cap (每日最多 K 只)
        """
        s = self._settings
        if not signals:
            return signals

        profit_regime = ctx.profit_effect.regime.value if ctx.profit_effect else None

        # ── 1. Dynamic score threshold + core factor express ──
        min_score = _dynamic_min_score(
            s.signal_min_score,
            ctx.sentiment,
            ctx.sentiment_cycle,
            profit_regime=profit_regime,
        )
        above = [sig for sig in signals if sig.composite_score >= min_score]
        # 核心因子直通: 综合分略低但核心因子极强的票放行
        below = [sig for sig in signals if sig.composite_score < min_score]
        express = []
        for sig in below:
            # 不得低于 min_score - 10
            if sig.composite_score < min_score - 10:
                continue
            if _core_factor_express(sig):
                express.append(sig)
                logger.info(
                    "核心因子直通: %s (%s) score=%.0f < min=%.0f",
                    sig.ts_code,
                    sig.name,
                    sig.composite_score,
                    min_score,
                )
        signals = above + express
        if not signals:
            return signals

        # ── 2. Per-theme concentration (分层版: leader+follower 可双持) ──
        max_theme = s.signal_max_per_theme
        theme_signals: dict[str, list[TradingSignal]] = {}
        theme_filtered: list[TradingSignal] = []
        for sig in signals:
            key = sig.theme
            if not key:
                # 无题材标记的信号不受题材限制
                theme_filtered.append(sig)
                continue
            existing = theme_signals.get(key, [])
            if len(existing) < max_theme:
                theme_filtered.append(sig)
                existing.append(sig)
                theme_signals[key] = existing
            elif len(existing) == max_theme:
                # 允许同题材 leader+follower 双持（板型多样化）
                existing_types = {s_.signal_type.value for s_ in existing}
                if sig.signal_type.value not in existing_types:
                    theme_filtered.append(sig)
                    existing.append(sig)
                else:
                    logger.debug(
                        "题材集中度过滤: %s (%s) — 题材 '%s' 已达上限",
                        sig.ts_code,
                        sig.name,
                        key,
                    )
            else:
                logger.debug(
                    "题材集中度过滤: %s (%s) — 题材 '%s' 已达上限",
                    sig.ts_code,
                    sig.name,
                    key,
                )
        signals = theme_filtered

        # ── 3. Per-type concentration ──
        max_type = s.signal_max_per_type
        type_counts: dict[str, int] = {}
        type_filtered: list[TradingSignal] = []
        for sig in signals:
            key = sig.signal_type.value
            count = type_counts.get(key, 0)
            if count < max_type:
                type_filtered.append(sig)
                type_counts[key] = count + 1
            else:
                logger.debug(
                    "板型集中度过滤: %s (%s) — %s 已达上限 %d",
                    sig.ts_code,
                    sig.name,
                    key,
                    max_type,
                )
        signals = type_filtered

        # ── 4. TopK daily cap (dynamic) ──
        cycle_phase = ctx.sentiment_cycle.phase.value if ctx.sentiment_cycle else None
        score_delta = ctx.sentiment_cycle.score_delta if ctx.sentiment_cycle else 0.0
        effective_top_k = min(
            _dynamic_top_k(profit_regime, cycle_phase, score_delta),
            s.signal_top_k,
        )
        if effective_top_k <= 0:
            return []
        if len(signals) > effective_top_k:
            # 检查边界分差: 与 cutoff 分差 < 5 的额外信号可多放1只
            cutoff = signals[effective_top_k - 1].composite_score
            extended = [
                sig for sig in signals[effective_top_k:] if sig.composite_score >= cutoff - 5
            ]
            logger.info(
                "TopK 截断: %d → %d (+%d 边界放行)",
                len(signals),
                effective_top_k,
                min(len(extended), 1),
            )
            signals = signals[:effective_top_k] + extended[:1]

        return signals

    # -- internals -----------------------------------------------------------

    def _enhance_reasons_with_llm(
        self,
        signals: list[TradingSignal],
        ctx: DailyAnalysisContext,
    ) -> list[TradingSignal]:
        """Replace rule-based reasons with LLM-generated ones (batch call)."""
        try:
            from hit_astocker.llm.narrative_gen import generate_signal_reasons

            reason_map = generate_signal_reasons(
                self._llm_client,
                signals,
                event_result=ctx.event,
                cache=self._llm_cache,
            )
        except Exception:
            logger.warning("LLM signal reason enhancement failed", exc_info=True)
            return signals

        if not reason_map:
            return signals

        enhanced = []
        for sig in signals:
            llm_reason = reason_map.get(sig.ts_code)
            if llm_reason:
                sig = TradingSignal(
                    trade_date=sig.trade_date,
                    ts_code=sig.ts_code,
                    name=sig.name,
                    signal_type=sig.signal_type,
                    composite_score=sig.composite_score,
                    risk_level=sig.risk_level,
                    position_hint=sig.position_hint,
                    factors=sig.factors,
                    reason=llm_reason,
                    score_source=sig.score_source,
                    theme=sig.theme,
                )
            enhanced.append(sig)
        return enhanced

    @staticmethod
    def _build_reason(candidate, sentiment, lianban, event_result=None) -> str:
        parts = []
        f = candidate.factors

        # ── Signal-type specific lead reason ──
        if candidate.signal_type == "FIRST_BOARD":
            sq = f.get("seal_quality", 0)
            if sq >= 80:
                parts.append("封板强度优秀")
            elif sq >= 60:
                parts.append("封板质量良好")
        elif candidate.signal_type == "FOLLOW_BOARD":
            hm = f.get("height_momentum", 0)
            surv = f.get("survival", 0)
            if hm >= 80:
                parts.append("最佳接力位")
            elif hm >= 55:
                parts.append("趋势确认")
            elif hm >= 30:
                parts.append("高位接力(衰减中)")
            else:
                parts.append("极高位博弈(衰减严重)")
            if surv >= 70:
                parts.append(f"晋级率{surv:.0f}")
            elif surv < 40:
                parts.append(f"晋级率偏低{surv:.0f}")
        elif candidate.signal_type == "SECTOR_LEADER":
            th = f.get("theme_heat", 0)
            lp = f.get("leader_position", 0)
            if lp >= 90:
                parts.append("板块龙一辨识度高")
            elif lp >= 70:
                parts.append("板块龙二跟涨")
            else:
                parts.append("板块龙头")
            if th >= 80:
                parts.append(f"题材热度{th:.0f}")

        # ── Common factor reasons (shared) ──
        if f.get("sentiment", 0) >= 65:
            parts.append("情绪偏暖")
        if f.get("sector", 0) >= 80:
            parts.append("热点板块")
        if f.get("dragon_tiger", 0) >= 70:
            parts.append("游资关注")
        if f.get("auction_quality", 0) >= 70:
            parts.append("竞价承接强")
        if f.get("capital_flow", 0) >= 70:
            parts.append("主力净流入")
        if f.get("northbound", 0) >= 70:
            parts.append("北向买入")
        if f.get("technical_form", 0) >= 75:
            parts.append("技术良好")

        if event_result:
            ev_map = {ev.ts_code: ev for ev in event_result.stock_events}
            ev = ev_map.get(candidate.ts_code)
            if ev and ev.event_weight >= 0.75:
                parts.append(f"事件催化({ev.event_type})")

        if f.get("stock_sentiment", 0) >= 70:
            parts.append("个股情绪强")

        return "; ".join(parts) if parts else "综合评分达标"


# ── Dynamic threshold ────────────────────────────────────────────────


def _core_factor_express(sig: TradingSignal) -> bool:
    """核心因子极强时允许绕过动态评分阈值 (直通通道).

    按 signal_type 分层判定:
    - FIRST_BOARD: 封板质量≥75 AND (竞价≥70 OR 题材热度≥75)
    - FOLLOW_BOARD: 生存率≥60 AND 高度动能≥60
    - SECTOR_LEADER: 题材热度≥80 AND 龙头地位≥85
    """
    f = sig.factors
    sig_type = sig.signal_type.value

    if sig_type == "FIRST_BOARD":
        sq = f.get("seal_quality", 0)
        aq = f.get("auction_quality", 0)
        th = f.get("theme_heat", 0)
        return sq >= 75 and (aq >= 70 or th >= 75)

    if sig_type == "FOLLOW_BOARD":
        surv = f.get("survival", 0)
        hm = f.get("height_momentum", 0)
        return surv >= 60 and hm >= 60

    if sig_type == "SECTOR_LEADER":
        th = f.get("theme_heat", 0)
        lp = f.get("leader_position", 0)
        return th >= 80 and lp >= 85

    return False


def _dynamic_min_score(
    base: float,
    sentiment: SentimentScore,
    cycle: SentimentCycle | None,
    profit_regime: str | None = None,
) -> float:
    """Compute adaptive score threshold from market regime + sentiment cycle.

    v16 放宽: 降低各环节惩罚幅度, 让更多信号进入回测评估.
    基准 50 → STRONG_BULL 可放宽到 45, STRONG_BEAR 收紧到 55.
    ICE/RETREAT +5, DIVERGE +3, REPAIR 不加 (修复期鼓励参与).
    """
    threshold = base

    # ── 1. Market regime adjustment ──
    ctx = sentiment.market_context
    if ctx:
        regime = ctx.market_regime
        regime_adj = {
            "STRONG_BULL": -5,
            "BULL": -3,
            "NEUTRAL": 0,
            "BEAR": +3,
            "STRONG_BEAR": +5,
        }
        threshold += regime_adj.get(regime, 0)

    # ── 2. Sentiment cycle adjustment ──
    if cycle:
        phase = cycle.phase
        if phase in (CyclePhase.ICE, CyclePhase.RETREAT):
            threshold += 5
        elif phase == CyclePhase.DIVERGE:
            threshold += 3
        elif phase == CyclePhase.REPAIR:
            pass  # 修复期是好入场时机, 不加惩罚
        elif phase == CyclePhase.CLIMAX and cycle.score_delta < -1:
            threshold += 5  # 高潮末期: 适度收紧
        elif phase == CyclePhase.FERMENT:
            threshold -= 3

    # ── 3. Profit regime adjustment ──
    if profit_regime == "WEAK":
        threshold += 3

    return max(30.0, min(65.0, threshold))  # clamp to [30, 65]


def _dynamic_top_k(
    profit_regime: str | None,
    cycle_phase: str | None,
    score_delta: float,
) -> int:
    """Compute dynamic daily signal cap based on market state.

    放宽后 (v16): FROZEN 允许 1 个, WEAK 允许 2 个, 其余 3-5 个.
    保证回测有足够样本量做统计分析.
    """
    if profit_regime == "FROZEN":
        return 1  # 极端行情仍允许极强信号

    base = 5  # align with settings.signal_top_k

    if profit_regime == "WEAK":
        return 2

    if profit_regime == "NORMAL":
        if cycle_phase == "FERMENT":
            return base
        return 3

    if profit_regime == "STRONG":
        if cycle_phase in ("FERMENT", "CLIMAX") and score_delta >= 0:
            return base
        if cycle_phase == "CLIMAX" and score_delta < 0:
            return 2
        return base

    # Unknown/None regime
    return 3

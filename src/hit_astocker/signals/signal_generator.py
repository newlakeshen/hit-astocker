"""Signal generation engine — two-stage pipeline.

Stage 1 (Hard filter): Remove non-tradeable samples via rule-based gates.
Stage 2 (Cross-sectional ranking): Score survivors using either:
  - ML model (logistic / GBDT, when trained model exists)
  - Rule-based weighted scoring (fallback)

Risk assessment runs AFTER scoring to determine position sizing.

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
from hit_astocker.models.signal import RiskLevel, SignalType, TradingSignal
from hit_astocker.signals.composite_scorer import CompositeScorer
from hit_astocker.signals.feature_builder import build_feature_matrix
from hit_astocker.signals.ranking_model import RankingModel
from hit_astocker.signals.risk_assessor import RiskAssessor
from hit_astocker.signals.stage1_filter import Stage1Filter

logger = logging.getLogger(__name__)


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
        # Try to load ML ranking model
        self._ranking_model = RankingModel()
        model_path = Path(self._settings.db_path).parent / "ranking_model.pkl"
        self._use_ml = self._ranking_model.load(model_path)
        if self._use_ml:
            logger.info("ML ranking model loaded — using two-stage pipeline")

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

        # ── Optional: LLM-enhanced signal reasons ──
        if self._llm_client is not None and signals:
            signals = self._enhance_reasons_with_llm(signals, ctx)

        return signals

    # -- Stage 2a: ML-based ranking ------------------------------------------

    def _ml_rank(self, candidates, ctx: DailyAnalysisContext) -> list[TradingSignal]:
        """Stage 2 (ML): score candidates using trained model."""
        # Build feature matrix
        features = build_feature_matrix(
            candidates, ctx.sentiment_cycle, ctx.coverage,
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
                candidate, ctx.sentiment, cycle=ctx.sentiment_cycle,
            )
            if risk == RiskLevel.NO_GO:
                continue

            position = RiskAssessor.position_hint(risk)
            reason = self._build_reason(candidate, ctx.sentiment, ctx.lianban, ctx.event)

            signals.append(TradingSignal(
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
            ))

        return signals

    # -- Stage 2b: Rule-based ranking (fallback) -----------------------------

    def _rule_rank(self, candidates, ctx: DailyAnalysisContext) -> list[TradingSignal]:
        """Stage 2 (rules): use weighted composite score for ranking."""
        signals = []
        for candidate in candidates:
            risk = self._risk_assessor.assess(
                candidate, ctx.sentiment, cycle=ctx.sentiment_cycle,
            )
            if risk == RiskLevel.NO_GO:
                continue

            position = RiskAssessor.position_hint(risk)
            reason = self._build_reason(candidate, ctx.sentiment, ctx.lianban, ctx.event)

            signals.append(TradingSignal(
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
            ))

        return signals

    # -- internals -----------------------------------------------------------

    def _enhance_reasons_with_llm(
        self, signals: list[TradingSignal], ctx: DailyAnalysisContext,
    ) -> list[TradingSignal]:
        """Replace rule-based reasons with LLM-generated ones (batch call)."""
        try:
            from hit_astocker.llm.narrative_gen import generate_signal_reasons
            reason_map = generate_signal_reasons(
                self._llm_client, signals,
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

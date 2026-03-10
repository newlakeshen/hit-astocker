"""Signal generation engine.

Produces actionable trading signals by combining composite scores and risk assessment.
Supports two entry points:
  - generate_from_context(ctx) — preferred, uses pre-computed DailyAnalysisContext
  - generate(trade_date)       — convenience wrapper, builds context internally
"""

import sqlite3
from datetime import date

from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.daily_context import DailyAnalysisContext, build_daily_context
from hit_astocker.models.signal import RiskLevel, SignalType, TradingSignal
from hit_astocker.signals.composite_scorer import CompositeScorer
from hit_astocker.signals.risk_assessor import RiskAssessor
from hit_astocker.utils.stock_filter import should_exclude


class SignalGenerator:
    def __init__(self, conn: sqlite3.Connection, settings: Settings | None = None):
        self._conn = conn
        self._settings = settings or get_settings()
        self._scorer = CompositeScorer(self._settings)
        self._risk_assessor = RiskAssessor()

    # -- public API ----------------------------------------------------------

    def generate(self, trade_date: date) -> list[TradingSignal]:
        """Build context internally and generate signals (standalone usage)."""
        ctx = build_daily_context(self._conn, self._settings, trade_date)
        return self.generate_from_context(ctx)

    def generate_from_context(self, ctx: DailyAnalysisContext) -> list[TradingSignal]:
        """Generate signals from a pre-computed analysis context."""
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
        )

        signals = []
        for candidate in scored:
            if should_exclude(candidate.ts_code, candidate.name):
                continue

            risk = self._risk_assessor.assess(candidate, ctx.sentiment)
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
            ))

        return sorted(signals, key=lambda s: s.composite_score, reverse=True)

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _build_reason(candidate, sentiment, lianban, event_result=None) -> str:
        parts = []

        # Signal-type specific lead reason
        if candidate.signal_type == "FOLLOW_BOARD":
            survival = candidate.factors.get("lianban_survival", 0)
            if survival >= 70:
                parts.append("连板晋级概率高")
            else:
                parts.append("连板跟进")
        elif candidate.signal_type == "SECTOR_LEADER":
            parts.append("板块龙头领涨")

        # Common factor reasons
        if candidate.factors.get("sentiment", 0) >= 65:
            parts.append("市场情绪偏暖")
        if candidate.factors.get("seal_quality", 0) >= 70:
            parts.append("封板质量优秀")
        if candidate.factors.get("sector", 0) >= 80:
            parts.append("属于当日热点板块")
        if candidate.factors.get("dragon_tiger", 0) >= 70:
            parts.append("龙虎榜资金关注")
        if candidate.factors.get("capital_flow", 0) >= 70:
            parts.append("主力资金净流入")
        if candidate.factors.get("northbound", 0) >= 70:
            parts.append("北向资金买入")
        if candidate.factors.get("technical_form", 0) >= 75:
            parts.append("技术形态良好")

        if event_result:
            ev_map = {ev.ts_code: ev for ev in event_result.stock_events}
            ev = ev_map.get(candidate.ts_code)
            if ev and ev.event_weight >= 0.75:
                parts.append(f"事件催化({ev.event_type})")

        if candidate.factors.get("stock_sentiment", 0) >= 70:
            parts.append("个股情绪强势")

        return "; ".join(parts) if parts else "综合评分达标"

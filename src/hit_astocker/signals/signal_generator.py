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
            if hm >= 90:
                parts.append("2板最佳接力位")
            elif hm >= 75:
                parts.append("3板趋势确认")
            else:
                parts.append("高位接力")
            if surv >= 70:
                parts.append(f"晋级率{surv:.0f}%")
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

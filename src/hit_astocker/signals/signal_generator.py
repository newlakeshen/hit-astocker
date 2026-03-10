"""Signal generation engine (enhanced with survival rate, northbound, technical form).

Produces actionable trading signals by combining composite scores and risk assessment.
Integrates: event classification, 8-factor stock sentiment, board survival stats,
northbound capital, and technical form analysis.
"""

import sqlite3
from datetime import date

from hit_astocker.analyzers.board_survival import BoardSurvivalAnalyzer
from hit_astocker.analyzers.dragon_tiger import DragonTigerAnalyzer
from hit_astocker.analyzers.event_classifier import EventClassifier
from hit_astocker.analyzers.firstboard import FirstBoardAnalyzer
from hit_astocker.analyzers.lianban import LianbanAnalyzer
from hit_astocker.analyzers.moneyflow import MoneyFlowAnalyzer
from hit_astocker.analyzers.sector_rotation import SectorRotationAnalyzer
from hit_astocker.analyzers.sentiment import SentimentAnalyzer
from hit_astocker.analyzers.stock_sentiment import StockSentimentAnalyzer
from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.signal import RiskLevel, SignalType, TradingSignal
from hit_astocker.repositories.hsgt_repo import HsgtTop10Repository
from hit_astocker.signals.composite_scorer import CompositeScorer
from hit_astocker.signals.risk_assessor import RiskAssessor
from hit_astocker.utils.stock_filter import should_exclude


class SignalGenerator:
    def __init__(self, conn: sqlite3.Connection, settings: Settings | None = None):
        self._conn = conn
        self._settings = settings or get_settings()
        self._sentiment_analyzer = SentimentAnalyzer(conn, self._settings)
        self._firstboard_analyzer = FirstBoardAnalyzer(conn, self._settings)
        self._lianban_analyzer = LianbanAnalyzer(conn)
        self._sector_analyzer = SectorRotationAnalyzer(conn)
        self._dragon_analyzer = DragonTigerAnalyzer(conn)
        self._moneyflow_analyzer = MoneyFlowAnalyzer(conn)
        self._event_classifier = EventClassifier(conn)
        self._stock_sentiment_analyzer = StockSentimentAnalyzer(conn)
        self._board_survival_analyzer = BoardSurvivalAnalyzer(conn)
        self._hsgt_repo = HsgtTop10Repository(conn)
        self._scorer = CompositeScorer(self._settings)
        self._risk_assessor = RiskAssessor()

    def generate(self, trade_date: date) -> list[TradingSignal]:
        # Phase 1: Independent analyzers (sequential — single SQLite connection)
        sentiment = self._sentiment_analyzer.analyze(trade_date)
        firstboard_results = self._firstboard_analyzer.analyze(trade_date)
        lianban = self._lianban_analyzer.analyze(trade_date)
        sector = self._sector_analyzer.analyze(trade_date)
        dragon = self._dragon_analyzer.analyze(trade_date)
        event_result = self._event_classifier.analyze(trade_date)
        survival_model = self._board_survival_analyzer.compute_model(trade_date)
        hsgt_net_map = self._hsgt_repo.find_net_buyers_by_date(trade_date)

        # Phase 2: Dependent analyzers (need firstboard candidates)
        candidate_codes = [fb.ts_code for fb in firstboard_results]
        moneyflow = self._moneyflow_analyzer.analyze(trade_date, candidate_codes)
        stock_sentiments = self._stock_sentiment_analyzer.analyze(trade_date, candidate_codes)

        # Score candidates (10-factor composite)
        scored = self._scorer.score(
            sentiment, firstboard_results, lianban, sector, dragon, moneyflow,
            event_result=event_result,
            stock_sentiments=stock_sentiments,
            survival_model=survival_model,
            hsgt_net_map=hsgt_net_map,
        )

        # Generate signals with risk assessment
        signals = []
        for candidate in scored:
            if should_exclude(candidate.ts_code, candidate.name):
                continue

            risk = self._risk_assessor.assess(candidate, sentiment)
            if risk == RiskLevel.NO_GO:
                continue

            position = RiskAssessor.position_hint(risk)
            reason = self._build_reason(candidate, sentiment, lianban, event_result)

            signals.append(TradingSignal(
                trade_date=trade_date,
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

    @staticmethod
    def _build_reason(candidate, sentiment, lianban, event_result=None) -> str:
        parts = []
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

        # Northbound reason
        if candidate.factors.get("northbound", 0) >= 70:
            parts.append("北向资金买入")

        # Technical form reason
        if candidate.factors.get("technical_form", 0) >= 75:
            parts.append("技术形态良好")

        # Event-driven reason
        if event_result:
            ev_map = {ev.ts_code: ev for ev in event_result.stock_events}
            ev = ev_map.get(candidate.ts_code)
            if ev and ev.event_weight >= 0.75:
                parts.append(f"事件催化({ev.event_type})")

        # Stock sentiment reason
        if candidate.factors.get("stock_sentiment", 0) >= 70:
            parts.append("个股情绪强势")

        return "; ".join(parts) if parts else "综合评分达标"

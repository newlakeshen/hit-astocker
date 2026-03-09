"""Stock buy/sell prediction engine.

Combines money flow factors with board (涨停) characteristics,
sector analysis, and market sentiment to generate ranked
buy/sell candidate lists.

Prediction dimensions:
1. Flow factors (7 sub-factors) - 40% weight
2. Board characteristics (涨停板特征) - 25% weight
3. Market sentiment (市场情绪) - 15% weight
4. Sector momentum (板块动量) - 10% weight
5. Dragon-tiger institutional signal - 10% weight
"""

import sqlite3
from datetime import date

from hit_astocker.analyzers.dragon_tiger import DragonTigerAnalyzer
from hit_astocker.analyzers.flow_factors import FlowFactorEngine, FlowFactorResult
from hit_astocker.analyzers.sector_rotation import SectorRotationAnalyzer
from hit_astocker.analyzers.sentiment import SentimentAnalyzer
from hit_astocker.config.settings import Settings, get_settings
from hit_astocker.models.prediction import (
    Direction,
    FactorScore,
    PredictionReport,
    StockPrediction,
)
from hit_astocker.repositories.daily_bar_repo import DailyBarRepository
from hit_astocker.repositories.limit_repo import LimitListRepository
from hit_astocker.repositories.moneyflow_detail_repo import MoneyFlowDetailRepository
from hit_astocker.repositories.moneyflow_repo import MoneyFlowRepository
from hit_astocker.utils.stock_filter import should_exclude


class StockPredictor:
    def __init__(self, conn: sqlite3.Connection, settings: Settings | None = None):
        self._conn = conn
        self._settings = settings or get_settings()
        self._flow_engine = FlowFactorEngine(conn)
        self._sentiment_analyzer = SentimentAnalyzer(conn, self._settings)
        self._sector_analyzer = SectorRotationAnalyzer(conn)
        self._dragon_analyzer = DragonTigerAnalyzer(conn)
        self._limit_repo = LimitListRepository(conn)
        self._bar_repo = DailyBarRepository(conn)
        self._detail_repo = MoneyFlowDetailRepository(conn)
        self._ths_repo = MoneyFlowRepository(conn)

    def predict(
        self, trade_date: date, top_n: int = 20
    ) -> PredictionReport:
        """Generate buy/sell predictions for a trading date."""
        # 1. Market-level analysis
        sentiment = self._sentiment_analyzer.analyze(trade_date)
        sector = self._sector_analyzer.analyze(trade_date)
        dragon = self._dragon_analyzer.analyze(trade_date)

        top_sector_names = {s.name for s in sector.top_sectors[:5]}

        # 2. Get candidate pool: top main force inflow stocks
        top_inflow = self._detail_repo.find_top_main_force_inflow(trade_date, top_n=100)
        inflow_codes = [f.ts_code for f in top_inflow]

        # Also include limit-up stocks
        limit_up_records = self._limit_repo.find_records_by_date(trade_date)
        limit_up_codes = {r.ts_code for r in limit_up_records if r.limit.value == "U"}
        limit_up_info = {r.ts_code: r for r in limit_up_records}

        # Merge candidate pool
        all_codes = list(dict.fromkeys(inflow_codes + list(limit_up_codes)))  # deduplicate

        # 3. Get daily bar info for names and filtering
        bars_today = {b.ts_code: b for b in self._bar_repo.find_records_by_date(trade_date)}
        ths_today = {r.ts_code: r for r in self._ths_repo.find_records_by_date(trade_date)}

        # 4. Compute flow factors for all candidates
        buy_candidates = []
        sell_candidates = []

        for ts_code in all_codes:
            bar = bars_today.get(ts_code)
            ths = ths_today.get(ts_code)
            name = ths.name if ths else (bar.ts_code if bar else ts_code)

            if should_exclude(ts_code, name):
                continue

            flow_result = self._flow_engine.compute_factors(ts_code, trade_date)
            if flow_result is None:
                continue

            # Compute board characteristic score
            board_score = self._board_score(ts_code, limit_up_info, trade_date)

            # Sector score
            industry = ""
            if ts_code in limit_up_info:
                industry = limit_up_info[ts_code].industry
            sector_score = 80.0 if industry in top_sector_names else 40.0

            # Dragon-tiger score
            dt_score = 50.0
            inst_net = dragon.institutional_net_buy.get(ts_code, 0)
            if inst_net > 0:
                dt_score = 80.0
            if ts_code in dragon.cooperation_flags:
                dt_score = 90.0

            # Composite prediction score
            composite = (
                0.40 * flow_result.composite_score
                + 0.25 * board_score
                + 0.15 * sentiment.overall_score
                + 0.10 * sector_score
                + 0.10 * dt_score
            )

            # Predicted pct change heuristic
            predicted_pct = self._estimate_pct(flow_result, board_score, sentiment.overall_score)

            factors = (
                flow_result.main_force_momentum,
                flow_result.smart_money,
                flow_result.order_structure,
                flow_result.flow_price_divergence,
                flow_result.accumulation,
                flow_result.volume_price,
                flow_result.flow_consistency,
                FactorScore("涨停板特征", board_score, board_score, 0.25, ""),
                FactorScore("板块动量", sector_score, sector_score, 0.10, industry),
                FactorScore("龙虎榜信号", dt_score, dt_score, 0.10, ""),
            )

            reason_parts = []
            if flow_result.composite_score >= 65:
                reason_parts.append("资金面强势")
            if flow_result.main_force_momentum.score >= 70:
                reason_parts.append(flow_result.main_force_momentum.description)
            if flow_result.smart_money.score >= 70:
                reason_parts.append(flow_result.smart_money.description)
            if flow_result.accumulation.score >= 70:
                reason_parts.append(flow_result.accumulation.description)
            if flow_result.flow_price_divergence.score >= 70:
                reason_parts.append(flow_result.flow_price_divergence.description)
            if board_score >= 70:
                reason_parts.append("涨停板质量高")
            if sector_score >= 70:
                reason_parts.append(f"热点板块({industry})")
            if dt_score >= 70:
                reason_parts.append("龙虎榜资金关注")

            close_price = bar.close if bar else 0.0
            pct_chg = bar.pct_chg if bar else 0.0

            prediction = StockPrediction(
                trade_date=trade_date,
                ts_code=ts_code,
                name=name,
                direction=Direction.BUY if flow_result.direction_bias > 0 else Direction.SELL,
                confidence=round(composite, 1),
                predicted_pct=round(predicted_pct, 2),
                factor_scores=factors,
                reason="; ".join(reason_parts) if reason_parts else "综合因子达标",
                sector=industry,
                close=close_price,
                pct_chg=pct_chg,
            )

            if flow_result.direction_bias > 0 and composite >= 55:
                buy_candidates.append(prediction)
            elif flow_result.direction_bias < -5 and composite < 45:
                sell_candidates.append(prediction)

        # Sort
        buy_sorted = sorted(buy_candidates, key=lambda p: p.confidence, reverse=True)[:top_n]
        sell_sorted = sorted(sell_candidates, key=lambda p: p.confidence)[:top_n]

        market_desc = f"{sentiment.description} | 涨停{sentiment.limit_up_count}家 炸板{sentiment.broken_count}家"

        return PredictionReport(
            trade_date=trade_date,
            buy_candidates=tuple(buy_sorted),
            sell_candidates=tuple(sell_sorted),
            market_score=sentiment.overall_score,
            market_description=market_desc,
        )

    def _board_score(self, ts_code: str, limit_up_info: dict, trade_date: date) -> float:
        """Score based on limit-up board characteristics."""
        if ts_code not in limit_up_info:
            return 40.0  # Not on board today → neutral

        record = limit_up_info[ts_code]
        score = 50.0

        # Seal time bonus
        if record.first_time and record.first_time < "10:00":
            score += 15
        elif record.first_time and record.first_time < "10:30":
            score += 10

        # Purity bonus
        if record.open_times == 0:
            score += 15
        elif record.open_times == 1:
            score += 5

        # Consecutive board bonus
        if record.limit_times >= 3:
            score += 15
        elif record.limit_times >= 2:
            score += 10

        # Seal strength
        if record.float_mv > 0 and record.limit_amount / record.float_mv > 0.05:
            score += 5

        return min(score, 100)

    @staticmethod
    def _estimate_pct(flow: FlowFactorResult, board_score: float, sentiment: float) -> float:
        """Rough heuristic for expected next-day % change."""
        base = 0.0

        # Flow-driven estimate
        if flow.direction_bias > 20:
            base += 2.0 + flow.direction_bias / 50
        elif flow.direction_bias > 0:
            base += 0.5 + flow.direction_bias / 30
        elif flow.direction_bias < -20:
            base -= 2.0 + abs(flow.direction_bias) / 50
        else:
            base -= abs(flow.direction_bias) / 40

        # Board bonus
        if board_score >= 70:
            base += 1.5
        elif board_score >= 50:
            base += 0.5

        # Sentiment dampener
        if sentiment < 40:
            base *= 0.5
        elif sentiment > 70:
            base *= 1.2

        return max(-10, min(10, base))

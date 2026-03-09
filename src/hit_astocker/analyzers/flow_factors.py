"""Money flow factor engine.

Computes comprehensive money flow factors for each stock:
1. Main force momentum (主力动量) - 大单+特大单净流入趋势
2. Smart money indicator (聪明钱) - 特大单占比和方向
3. Order structure (订单结构) - 各档位资金分布
4. Flow-price divergence (量价背离) - 资金流向与价格走势的背离
5. Accumulation/distribution (吸筹/派发) - 持续流入/流出检测
6. Volume-price relationship (量价关系) - 放量/缩量配合涨跌
7. Institutional flow (机构行为) - 大单持续性
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from hit_astocker.models.daily_bar import DailyBar
from hit_astocker.models.moneyflow_detail import MoneyFlowDetail
from hit_astocker.models.prediction import FactorScore
from hit_astocker.repositories.daily_bar_repo import DailyBarRepository
from hit_astocker.repositories.moneyflow_detail_repo import MoneyFlowDetailRepository
from hit_astocker.repositories.moneyflow_repo import MoneyFlowRepository
from hit_astocker.utils.date_utils import to_tushare_date


@dataclass(frozen=True)
class FlowFactorResult:
    """All flow factor scores for a single stock."""
    ts_code: str
    name: str
    trade_date: date
    # Individual factors
    main_force_momentum: FactorScore
    smart_money: FactorScore
    order_structure: FactorScore
    flow_price_divergence: FactorScore
    accumulation: FactorScore
    volume_price: FactorScore
    flow_consistency: FactorScore
    # Composite
    composite_score: float
    direction_bias: float  # >0 bullish, <0 bearish


class FlowFactorEngine:
    """Computes money flow factors for stock prediction."""

    def __init__(self, conn: sqlite3.Connection):
        self._detail_repo = MoneyFlowDetailRepository(conn)
        self._ths_repo = MoneyFlowRepository(conn)
        self._bar_repo = DailyBarRepository(conn)

    def compute_factors(
        self, ts_code: str, trade_date: date, lookback: int = 10
    ) -> FlowFactorResult | None:
        """Compute all flow factors for a stock."""
        start = trade_date - timedelta(days=lookback * 2)  # over-request for weekends

        flows = self._detail_repo.find_by_stock_range(ts_code, start, trade_date)
        bars = self._bar_repo.find_recent_bars(ts_code, trade_date, lookback)
        ths = self._ths_repo.find_by_stock(trade_date, ts_code)

        if not flows or not bars:
            return None

        today_flow = flows[-1] if flows else None
        if today_flow is None or today_flow.trade_date != trade_date:
            return None

        name = ths.name if ths else ""

        f1 = self._main_force_momentum(flows[-lookback:])
        f2 = self._smart_money(today_flow, flows[-lookback:])
        f3 = self._order_structure(today_flow)
        f4 = self._flow_price_divergence(flows[-5:], bars[-5:])
        f5 = self._accumulation(flows[-lookback:])
        f6 = self._volume_price(bars[-5:])
        f7 = self._flow_consistency(flows[-lookback:])

        # Weighted composite
        factors = [f1, f2, f3, f4, f5, f6, f7]
        composite = sum(f.score * f.weight for f in factors)

        # Direction bias: positive = bullish, negative = bearish
        bullish_signal = (f1.score - 50) * 0.25 + (f2.score - 50) * 0.20 + (f5.score - 50) * 0.25 + (f4.score - 50) * 0.15 + (f7.score - 50) * 0.15
        direction_bias = max(-100, min(100, bullish_signal))

        return FlowFactorResult(
            ts_code=ts_code,
            name=name,
            trade_date=trade_date,
            main_force_momentum=f1,
            smart_money=f2,
            order_structure=f3,
            flow_price_divergence=f4,
            accumulation=f5,
            volume_price=f6,
            flow_consistency=f7,
            composite_score=round(composite, 2),
            direction_bias=round(direction_bias, 2),
        )

    def batch_compute(
        self, ts_codes: list[str], trade_date: date, lookback: int = 10
    ) -> list[FlowFactorResult]:
        """Compute factors for a batch of stocks."""
        results = []
        for code in ts_codes:
            result = self.compute_factors(code, trade_date, lookback)
            if result is not None:
                results.append(result)
        return results

    # -------------------------------------------------------------------------
    # Factor implementations
    # -------------------------------------------------------------------------

    @staticmethod
    def _main_force_momentum(flows: list[MoneyFlowDetail]) -> FactorScore:
        """F1: 主力动量 - 大单+特大单净流入趋势和加速度.

        Measures:
        - Recent main force net inflow
        - Trend direction (increasing vs decreasing)
        - Acceleration (2nd derivative)
        """
        if len(flows) < 2:
            return FactorScore("主力动量", 0, 50, 0.20, "数据不足")

        nets = [f.main_force_net for f in flows]
        latest = nets[-1]

        # Trend: compare recent vs earlier half
        mid = len(nets) // 2
        recent_avg = sum(nets[mid:]) / max(len(nets[mid:]), 1)
        early_avg = sum(nets[:mid]) / max(len(nets[:mid]), 1)

        # Acceleration: last 3 days trend
        if len(nets) >= 3:
            accel = (nets[-1] - nets[-2]) - (nets[-2] - nets[-3])
        else:
            accel = 0

        # Score: normalize main force flow
        # Strong inflow: high score, strong outflow: low score
        score = 50.0
        if latest > 0:
            score = min(50 + latest / 500.0, 100)
        else:
            score = max(50 + latest / 500.0, 0)

        # Trend bonus/penalty
        if recent_avg > early_avg > 0:
            score = min(score + 10, 100)
            desc = "主力持续加仓"
        elif recent_avg > early_avg:
            score = min(score + 5, 100)
            desc = "主力流入增加"
        elif recent_avg < early_avg < 0:
            score = max(score - 10, 0)
            desc = "主力持续出逃"
        else:
            desc = "主力动量中性"

        # Acceleration bonus
        if accel > 0 and latest > 0:
            score = min(score + 5, 100)
            desc += ",加速流入"

        return FactorScore("主力动量", latest, round(score, 1), 0.20, desc)

    @staticmethod
    def _smart_money(today: MoneyFlowDetail, flows: list[MoneyFlowDetail]) -> FactorScore:
        """F2: 聪明钱指标 - 特大单行为分析.

        特大单(>=100万)代表机构/大户行为:
        - 特大单净流入方向
        - 特大单占比变化
        - 特大单与散户(小单)方向是否相反 (经典分歧信号)
        """
        elg_net = today.net_elg
        sm_net = today.net_sm
        elg_ratio = today.elg_ratio

        # Smart money divergence: institutions buy while retail sells
        divergence = elg_net > 0 and sm_net < 0

        # Historical ELG ratio trend
        elg_ratios = [f.elg_ratio for f in flows]
        avg_ratio = sum(elg_ratios) / max(len(elg_ratios), 1)

        score = 50.0
        if elg_net > 0:
            score = min(50 + elg_net / 300.0, 90)
        else:
            score = max(50 + elg_net / 300.0, 10)

        desc_parts = []
        if divergence:
            score = min(score + 15, 100)
            desc_parts.append("机构散户分歧(看多)")
        if elg_ratio > avg_ratio * 1.5:
            score = min(score + 5, 100)
            desc_parts.append("特大单活跃度上升")
        if elg_net < 0 and sm_net > 0:
            score = max(score - 10, 0)
            desc_parts.append("机构出货散户接盘")

        desc = "; ".join(desc_parts) if desc_parts else "聪明钱中性"

        return FactorScore("聪明钱", elg_net, round(score, 1), 0.18, desc)

    @staticmethod
    def _order_structure(today: MoneyFlowDetail) -> FactorScore:
        """F3: 订单结构 - 各档位资金分布健康度.

        健康买入结构: 大单+特大单主导 (主力驱动)
        不健康结构: 仅小单买入 (散户追涨)
        """
        total_buy = today.total_buy
        if total_buy <= 0:
            return FactorScore("订单结构", 0, 50, 0.10, "无成交")

        elg_buy_pct = today.buy_elg_amount / total_buy
        lg_buy_pct = today.buy_lg_amount / total_buy
        sm_buy_pct = today.buy_sm_amount / total_buy
        main_buy_pct = elg_buy_pct + lg_buy_pct

        # Healthy structure: main force dominates buying
        score = 50.0
        if main_buy_pct > 0.5:
            score = 75 + (main_buy_pct - 0.5) * 50
            desc = f"主力买入占{main_buy_pct:.0%}(健康)"
        elif main_buy_pct > 0.3:
            score = 55 + (main_buy_pct - 0.3) * 100
            desc = f"主力买入占{main_buy_pct:.0%}(一般)"
        else:
            score = 30 + main_buy_pct * 80
            desc = f"散户主导买入({sm_buy_pct:.0%})"
            if sm_buy_pct > 0.6:
                score = max(score - 10, 0)
                desc += "(警惕)"

        return FactorScore("订单结构", main_buy_pct * 100, round(min(score, 100), 1), 0.10, desc)

    @staticmethod
    def _flow_price_divergence(
        flows: list[MoneyFlowDetail], bars: list[DailyBar]
    ) -> FactorScore:
        """F4: 量价背离 - 资金流向与价格走势背离检测.

        关键信号:
        - 价格下跌但主力净流入 → 买入信号 (主力逆势吸筹)
        - 价格上涨但主力净流出 → 卖出信号 (主力逆势出货)
        """
        if len(flows) < 3 or len(bars) < 3:
            return FactorScore("量价背离", 0, 50, 0.15, "数据不足")

        # Price trend (sum of pct_chg)
        price_trend = sum(b.pct_chg for b in bars[-3:])
        # Flow trend (sum of main force net)
        flow_trend = sum(f.main_force_net for f in flows[-3:])

        score = 50.0
        if price_trend < -2 and flow_trend > 0:
            # Price down, money in → bullish divergence
            divergence_strength = min(abs(flow_trend) / 1000, 1.0)
            score = 70 + divergence_strength * 30
            desc = f"看多背离: 价跌{price_trend:.1f}%但主力流入"
        elif price_trend > 2 and flow_trend < 0:
            # Price up, money out → bearish divergence
            divergence_strength = min(abs(flow_trend) / 1000, 1.0)
            score = 30 - divergence_strength * 30
            desc = f"看空背离: 价涨{price_trend:.1f}%但主力流出"
        elif price_trend > 0 and flow_trend > 0:
            score = 60 + min(flow_trend / 2000, 1) * 20
            desc = "量价齐升(正常)"
        elif price_trend < 0 and flow_trend < 0:
            score = 40 - min(abs(flow_trend) / 2000, 1) * 20
            desc = "量价齐跌(弱势)"
        else:
            desc = "量价中性"

        return FactorScore("量价背离", flow_trend, round(max(0, min(100, score)), 1), 0.15, desc)

    @staticmethod
    def _accumulation(flows: list[MoneyFlowDetail]) -> FactorScore:
        """F5: 吸筹/派发 - 持续主力流入/流出检测.

        连续N日主力净流入 → 吸筹信号
        连续N日主力净流出 → 派发信号
        """
        if len(flows) < 3:
            return FactorScore("吸筹派发", 0, 50, 0.15, "数据不足")

        main_nets = [f.main_force_net for f in flows]

        # Count consecutive days of inflow/outflow from latest
        consec_in = 0
        consec_out = 0
        for net in reversed(main_nets):
            if net > 0:
                if consec_out == 0:
                    consec_in += 1
                else:
                    break
            elif net < 0:
                if consec_in == 0:
                    consec_out += 1
                else:
                    break
            else:
                break

        # Total accumulated flow
        total_flow = sum(main_nets)

        score = 50.0
        if consec_in >= 5:
            score = 90
            desc = f"强力吸筹: 连续{consec_in}日主力净流入"
        elif consec_in >= 3:
            score = 75
            desc = f"吸筹中: 连续{consec_in}日主力净流入"
        elif consec_out >= 5:
            score = 10
            desc = f"强力派发: 连续{consec_out}日主力净流出"
        elif consec_out >= 3:
            score = 25
            desc = f"派发中: 连续{consec_out}日主力净流出"
        elif total_flow > 0:
            score = 55 + min(total_flow / 5000, 1) * 20
            desc = f"累计净流入{total_flow:.0f}万"
        else:
            score = 45 + max(total_flow / 5000, -1) * 20
            desc = f"累计净流出{abs(total_flow):.0f}万"

        return FactorScore("吸筹派发", total_flow, round(score, 1), 0.15, desc)

    @staticmethod
    def _volume_price(bars: list[DailyBar]) -> FactorScore:
        """F6: 量价关系 - 放量/缩量配合涨跌分析.

        健康上涨: 放量上涨 + 缩量回调
        危险信号: 放量下跌 / 缩量上涨 (没量拉不动)
        """
        if len(bars) < 3:
            return FactorScore("量价关系", 0, 50, 0.10, "数据不足")

        latest = bars[-1]
        prev_vols = [b.vol for b in bars[:-1]]
        avg_vol = sum(prev_vols) / max(len(prev_vols), 1)

        vol_ratio = latest.vol / max(avg_vol, 1)

        score = 50.0
        if latest.pct_chg > 0 and vol_ratio > 1.5:
            score = 80
            desc = f"放量上涨(量比{vol_ratio:.1f})"
        elif latest.pct_chg > 0 and vol_ratio < 0.7:
            score = 40
            desc = f"缩量上涨(量比{vol_ratio:.1f})(持续性存疑)"
        elif latest.pct_chg < -2 and vol_ratio > 2.0:
            score = 15
            desc = f"放量大跌(量比{vol_ratio:.1f})(危险)"
        elif latest.pct_chg < 0 and vol_ratio < 0.7:
            score = 55
            desc = f"缩量回调(量比{vol_ratio:.1f})(正常)"
        elif latest.pct_chg > 3 and vol_ratio > 1.2:
            score = 75
            desc = f"量价配合良好"
        else:
            desc = f"量价关系中性(量比{vol_ratio:.1f})"

        return FactorScore("量价关系", vol_ratio, round(score, 1), 0.10, desc)

    @staticmethod
    def _flow_consistency(flows: list[MoneyFlowDetail]) -> FactorScore:
        """F7: 资金一致性 - 不同档位资金方向是否一致.

        强信号: 大中小单同方向净流入
        弱信号: 各档位方向混乱
        """
        if not flows:
            return FactorScore("资金一致性", 0, 50, 0.12, "数据不足")

        today = flows[-1]
        directions = {
            "特大单": 1 if today.net_elg > 0 else -1,
            "大单": 1 if today.net_lg > 0 else -1,
            "中单": 1 if today.net_md > 0 else -1,
            "小单": 1 if today.net_sm > 0 else -1,
        }

        positive_count = sum(1 for v in directions.values() if v > 0)

        if positive_count == 4:
            score = 90.0
            desc = "全档位净流入(强看多)"
        elif positive_count == 3:
            # Which one is negative?
            neg = [k for k, v in directions.items() if v < 0][0]
            if neg == "小单":
                score = 80.0
                desc = "大中单流入散户流出(主力看多)"
            else:
                score = 65.0
                desc = f"3档流入({neg}流出)"
        elif positive_count == 2:
            score = 50.0
            desc = "多空分歧"
        elif positive_count == 1:
            pos = [k for k, v in directions.items() if v > 0][0]
            if pos == "小单":
                score = 20.0
                desc = "仅散户流入(危险)"
            else:
                score = 35.0
                desc = f"仅{pos}流入"
        else:
            score = 10.0
            desc = "全档位净流出(强看空)"

        return FactorScore("资金一致性", positive_count, round(score, 1), 0.12, desc)
